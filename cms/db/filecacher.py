#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Contest Management System - http://cms-dev.github.io/
# Copyright © 2010-2014 Giovanni Mascellani <mascellani@poisson.phc.unipi.it>
# Copyright © 2010-2018 Stefano Maggiolo <s.maggiolo@gmail.com>
# Copyright © 2010-2012 Matteo Boscariol <boscarim@hotmail.com>
# Copyright © 2013 Luca Wehrstedt <luca.wehrstedt@gmail.com>
# Copyright © 2016 Luca Versari <veluca93@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Cache to store and retrieve files, assumed to be binary.

"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals
from future.builtins.disabled import *  # noqa
from future.builtins import *  # noqa

import atexit
import io
import logging
import os
import tempfile

import gevent

from sqlalchemy.exc import IntegrityError

from cmscommon.digest import Digester
from cms import config, mkdir, rmtree
from cms.db import SessionGen, FSObject, LargeObject


logger = logging.getLogger(__name__)


def copyfileobj(source_fobj, destination_fobj,
                buffer_size=io.DEFAULT_BUFFER_SIZE):
    """Read all content from one file object and write it to another.

    Repeatedly read from the given source file object, until no content
    is left, and at the same time write the content to the destination
    file object. Never read or write more than the given buffer size.
    Be cooperative with other greenlets by yielding often.

    source_fobj (fileobj): a file object open for reading, in either
        binary or text mode (doesn't need to be buffered).
    destination_fobj (fileobj): a file object open for writing, in the
        same mode as the source (doesn't need to be buffered).
    buffer_size (int): the size of the read/write buffer.

    """
    while True:
        buffer = source_fobj.read(buffer_size)
        if len(buffer) == 0:
            break
        while len(buffer) > 0:
            gevent.sleep(0)
            written = destination_fobj.write(buffer)
            # FIXME remove this when we drop py2
            if written is None:
                break
            buffer = buffer[written:]
        gevent.sleep(0)


class TombstoneError(RuntimeError):
    """An error that represents the file cacher trying to read
    files that have been deleted from the database.

    """
    pass


class FileCacherBackend(object):
    """Abstract base class for all FileCacher backends.

    """

    def get_file(self, digest):
        """Retrieve a file from the storage.

        digest (unicode): the digest of the file to retrieve.

        return (fileobj): a readable binary file-like object from which
            to read the contents of the file.

        raise (KeyError): if the file cannot be found.

        """
        raise NotImplementedError("Please subclass this class.")

    def create_file(self, digest):
        """Create an empty file that will live in the storage.

        Once the caller has written the contents to the file, the commit_file()
        method must be called to commit it into the store.

        digest (unicode): the digest of the file to store.

        return (fileobj): a writable binary file-like object on which
            to write the contents of the file, or None if the file is
            already stored.

        """
        raise NotImplementedError("Please subclass this class.")

    def commit_file(self, fobj, digest, desc=""):
        """Commit a file created by create_file() to be stored.

        Given a file object returned by create_file(), this function populates
        the database to record that this file now legitimately exists and can
        be used.

        fobj (fileobj): the object returned by create_file()
        digest (unicode): the digest of the file to store.
        desc (unicode): the optional description of the file to
            store, intended for human beings.

        return (bool): True if the file was committed successfully, False if
            there was already a file with the same digest in the database. This
            shouldn't make any difference to the caller, except for testing
            purposes!

        """
        raise NotImplementedError("Please subclass this class.")

    def describe(self, digest):
        """Return the description of a file given its digest.

        digest (unicode): the digest of the file to describe.

        return (unicode): the description of the file.

        raise (KeyError): if the file cannot be found.

        """
        raise NotImplementedError("Please subclass this class.")

    def get_size(self, digest):
        """Return the size of a file given its digest.

        digest (unicode): the digest of the file to calculate the size
            of.

        return (int): the size of the file, in bytes.

        raise (KeyError): if the file cannot be found.

        """
        raise NotImplementedError("Please subclass this class.")

    def delete(self, digest):
        """Delete a file from the storage.

        digest (unicode): the digest of the file to delete.

        """
        raise NotImplementedError("Please subclass this class.")

    def list(self):
        """List the files available in the storage.

        return ([(unicode, unicode)]): a list of pairs, each
            representing a file in the form (digest, description).

        """
        raise NotImplementedError("Please subclass this class.")


class FSBackend(FileCacherBackend):
    """This class implements a backend for FileCacher that keeps all
    the files in a file system directory, named after their digest. Of
    course this directory can be shared, for example with NFS, acting
    as an actual remote file storage.

    TODO: Actually store the descriptions, that get discarded at the
    moment.

    TODO: Use an additional level of directories, to alleviate the
    work of the file system driver (e.g., 'ROOT/a/abcdef...' instead
    of 'ROOT/abcdef...'.

    """

    def __init__(self, path):
        """Initialize the backend.

        path (string): the base path for the storage.

        """
        self.path = path

        # Create the directory if it doesn't exist
        try:
            os.makedirs(self.path)
        except OSError:
            pass

    def get_file(self, digest):
        """See FileCacherBackend.get_file().

        """
        file_path = os.path.join(self.path, digest)

        if not os.path.exists(file_path):
            raise KeyError("File not found.")

        return io.open(file_path, 'rb')

    def create_file(self, digest):
        """See FileCacherBackend.create_file().

        """
        # Check if the file already exists. Return None if so, to inform the
        # caller they don't need to store the file.
        file_path = os.path.join(self.path, digest)

        if os.path.exists(file_path):
            return None

        # Create a temporary file in the same directory
        temp_file = tempfile.NamedTemporaryFile('wb', delete=False,
                                                prefix=".tmp.",
                                                suffix=digest,
                                                dir=self.path)
        return temp_file

    def commit_file(self, fobj, digest, desc=""):
        """See FileCacherBackend.commit_file().

        """
        fobj.close()

        file_path = os.path.join(self.path, digest)
        # Move it into place in the cache. Skip if it already exists, and
        # delete the temporary file instead.
        if not os.path.exists(file_path):
            # There is a race condition here if someone else puts the file here
            # between checking and renaming. Put it doesn't matter in practice,
            # because rename will replace the file anyway (which should be
            # identical).
            os.rename(fobj.name, file_path)
            return True
        else:
            os.unlink(fobj.name)
            return False

    def describe(self, digest):
        """See FileCacherBackend.describe().

        """
        file_path = os.path.join(self.path, digest)

        if not os.path.exists(file_path):
            raise KeyError("File not found.")

        return ""

    def get_size(self, digest):
        """See FileCacherBackend.get_size().

        """
        file_path = os.path.join(self.path, digest)

        if not os.path.exists(file_path):
            raise KeyError("File not found.")

        return os.stat(file_path).st_size

    def delete(self, digest):
        """See FileCacherBackend.delete().

        """
        file_path = os.path.join(self.path, digest)

        try:
            os.unlink(file_path)
        except OSError:
            pass

    def list(self):
        """See FileCacherBackend.list().

        """
        return list((x, "") for x in os.listdir(self.path))


class DBBackend(FileCacherBackend):
    """This class implements an actual backend for FileCacher that
    stores the files as lobjects (encapsuled in a FSObject) into a
    PostgreSQL database.

    """

    def get_file(self, digest):
        """See FileCacherBackend.get_file().

        """
        with SessionGen() as session:
            fso = FSObject.get_from_digest(digest, session)

            if fso is None:
                raise KeyError("File not found.")

            return fso.get_lobject(mode='rb')

    def create_file(self, digest):
        """See FileCacherBackend.create_file().

        """
        with SessionGen() as session:
            fso = FSObject.get_from_digest(digest, session)

            # Check digest uniqueness
            if fso is not None:
                logger.debug("File %s already stored on database, not "
                             "sending it again.", digest)
                session.rollback()
                return None

            # If it is not already present, copy the file into the
            # lobject
            else:
                # Create the large object first. This should be populated
                # and committed before putting it into the FSObjects table.
                return LargeObject(0, mode='wb')

    def commit_file(self, fobj, digest, desc=""):
        """See FileCacherBackend.commit_file().

        """
        fobj.close()
        try:
            with SessionGen() as session:
                fso = FSObject(description=desc)
                fso.digest = digest
                fso.loid = fobj.loid

                session.add(fso)

                session.commit()

                logger.debug("File %s (%s) stored on the database.",
                            digest, desc)

        except IntegrityError:
            # If someone beat us to adding the same object to the database, we
            # should at least drop the large object.
            LargeObject.unlink(fobj.loid)
            logger.warning("File %s (%s) caused an IntegrityError, ignoring.",
                           digest, desc)
            return False
        return True

    def describe(self, digest):
        """See FileCacherBackend.describe().

        """
        with SessionGen() as session:
            fso = FSObject.get_from_digest(digest, session)

            if fso is None:
                raise KeyError("File not found.")

            return fso.description

    def get_size(self, digest):
        """See FileCacherBackend.get_size().

        """
        # TODO - The business logic may be moved in FSObject, for
        # better generality
        with SessionGen() as session:
            fso = FSObject.get_from_digest(digest, session)

            if fso is None:
                raise KeyError("File not found.")

            with fso.get_lobject(mode='rb') as lobj:
                return lobj.seek(0, io.SEEK_END)

    def delete(self, digest):
        """See FileCacherBackend.delete().

        """
        with SessionGen() as session:
            fso = FSObject.get_from_digest(digest, session)

            if fso is None:
                session.rollback()
                return

            fso.delete()

            session.commit()

    def list(self, session=None):
        """See FileCacherBackend.list().

        This implementation also accepts an additional (and optional)
        parameter: a SQLAlchemy session to use to query the database.

        session (Session|None): the session to use; if not given a
            temporary one will be created and used.

        """
        def _list(session):
            """Do the work assuming session is valid.

            """
            return list((x.digest, x.description)
                        for x in session.query(FSObject))

        if session is not None:
            return _list(session)
        else:
            with SessionGen() as session:
                return _list(session)


class NullBackend(FileCacherBackend):
    """This backend is always empty, it just drops each file that
    receives. It looks mostly like /dev/null. It is useful when you
    want to just rely on the caching capabilities of FileCacher for
    very short-lived and local storages.

    """

    def get_file(self, digest):
        raise KeyError("File not found.")

    def create_file(self, digest):
        return None

    def commit_file(self, fobj, digest, desc=""):
        return False

    def describe(self, digest):
        raise KeyError("File not found.")

    def get_size(self, digest):
        raise KeyError("File not found.")

    def delete(self, digest):
        pass

    def list(self):
        return list()

import boto3
import botocore
from  botocore.vendored import requests
class S3Backend(FileCacherBackend):
    class _RequestsBody(object):
        def __init__(self, requests_response):
            self.resp = requests_response

        def __enter__(self):
            return self.resp.raw

        def __exit__(self, exc_type, exc_value, traceback):
            self.resp.close()
            if exc_type or exc_value or traceback:
                return False
            return True


    class _S3Body(object):
        def __init__(self, streaming_body):
            self.body = streaming_body

        def __enter__(self):
            return self.body

        def __exit__(self, exc_type, exc_value, traceback):
            self.body.close()
            if exc_type or exc_value or traceback:
                return False
            return True

    def __init__(self, region, bucket, prefix='', s3_proxy=None, base_url_for_fetch=None):
        if s3_proxy:
            config = botocore.config.Config(proxies={'http': s3_proxy, 'https': s3_proxy})
        else:
            config = None
        self.s3 = boto3.client('s3', region, config=config)

        self.bucket = bucket
        self.prefix = prefix
        self.base_url_for_fetch = base_url_for_fetch
        if self.base_url_for_fetch:
            self.http = requests.Session()
        else:
            self.http = None

    def _s3_key(self, digest):
        return "%s%s/%s" % (self.prefix, digest[0:2], digest)

    def get_file(self, digest):
        key = self._s3_key(digest)
        if self.http:
            url = "%s%s" % (self.base_url_for_fetch, key)
            resp = self.http.get(url, timeout=5, stream=True)
            if resp.status_code == 404:
                resp.close()
                raise KeyError("File not found.")
            elif not resp.ok:
                resp.close()
                resp.raise_for_status()

            return S3Backend._RequestsBody(resp)
        else:
            try:
                resp = self.s3.get_object(
                        Bucket=self.bucket,
                        Key=key,
                    )
            except self.s3.exceptions.NoSuchKey:
                raise KeyError("File not found.")

            return S3Backend._S3Body(resp['Body'])

    def create_file(self, digest):
        temp_file = tempfile.NamedTemporaryFile('w+b', delete=False,
                                                prefix=".s3backendtmp.",
                                                suffix=digest)
        return temp_file

    def commit_file(self, fobj, digest, desc=""):
        key = self._s3_key(digest)
        try:
            self.s3.head_object(Bucket=self.bucket, Key=key)
            os.unlink(fobj.name)
            fobj.close()
            return None
        except botocore.exceptions.ClientError as e:
            if e.response.get('Error',{}).get('Code',None) == '404':
                pass
            else:
                fobj.close()
                raise e

        fobj.seek(0)
        self.s3.upload_fileobj(fobj, Bucket=self.bucket, Key=key)
        fobj.close()
        os.unlink(fobj.name)

    def _head_object(self, digest):
        try:
            return self.s3.head_object(Bucket=self.bucket, Key=self._s3_key(digest))
        except self.s3.exceptions.NoSuchKey:
            raise KeyError("File not found.")
        except botocore.exceptions.ClientError as e:
            if e.response.get('Error',{}).get('Code',None) == '404':
                raise KeyError("File not found.")
            else:
                raise e

    def describe(self, digest):
        self._head_object(digest)
        return ""

    def get_size(self, digest):
        return self._head_object(digest)['ContentLength']

    def delete(self, digest):
        key = self._s3_key(digest)
        try:
            self.s3.delete_object(Bucket=self.bucket, Key=key)
            return None
        except self.s3.exceptions.NoSuchKey:
            pass

    def list(self):
        paginator = self.s3.get_paginator('list_objects_v2')
        prefix = self.prefix if self.prefix and self.prefix != '' else None
        pager = paginator.paginate(Bucket=self.bucket,Prefix=prefix)

        result = [(content['Key'].split('/')[-1], "") for page in pager for content in pager['Contents']]
        return result



class FileCacher(object):
    """This class implement a local cache for files stored as FSObject
    in the database.

    """

    # This value is very arbitrary, and in this case we want it to be a
    # one-size-fits-all, since we use it for many conversions. It has
    # been chosen arbitrarily based on performance tests on my machine.
    # A few consideration on the value it could assume follow:
    # - The page size of large objects is LOBLKSIZE, which is BLCKSZ/4
    #   (BLCKSZ is the block size of the PostgreSQL database, which is
    #   set during pre-build configuration). BLCKSZ is by default 8192,
    #   therefore LOBLKSIZE is 2048. See:
    #   http://www.postgresql.org/docs/9.0/static/catalog-pg-largeobject.html
    # - The `io' module defines a DEFAULT_BUFFER_SIZE constant, whose
    #   value is 8192.
    # CHUNK_SIZE should be a multiple of these values.
    CHUNK_SIZE = 2 ** 14  # 16348

    # The fake digest used to mark a file as deleted in the backend.
    TOMBSTONE_DIGEST = "x"

    def __init__(self, service=None, path=None, null=False):
        """Initialize.

        By default the database-powered backend will be used, but this
        can be changed using the parameters.

        service (Service|None): the service we are running for. Only
            used if present to determine the location of the
            file-system cache (and to provide the shard number to the
            Sandbox... sigh!).
        path (string|None): if specified, back the FileCacher with a
            file system-based storage instead of the default
            database-based one. The specified directory will be used
            as root for the storage and it will be created if it
            doesn't exist.
        null (bool): if True, back the FileCacher with a NullBackend,
            that just discards every file it receives. This setting
            takes priority over path.

        """
        self.service = service

        if null:
            self.backend = NullBackend()
        elif path is None:
            if config.s3_backend_enabled:
                self.backend = S3Backend(
                        region=config.s3_backend_region,
                        bucket=config.s3_backend_bucket,
                        prefix=config.s3_backend_prefix,
                        s3_proxy=config.s3_backend_proxy,
                        base_url_for_fetch=config.s3_backend_fetch_base_url,
                        )
            else:
                self.backend = DBBackend()
        else:
            self.backend = FSBackend(path)

        if service is None:
            self.file_dir = tempfile.mkdtemp(dir=config.temp_dir)
            # Delete this directory on exit since it has a random name and
            # won't be used again.
            atexit.register(lambda: rmtree(self.file_dir))
        else:
            self.file_dir = os.path.join(
                config.cache_dir,
                "fs-cache-%s-%d" % (service.name, service.shard))

        self.temp_dir = os.path.join(self.file_dir, "_temp")

        if not mkdir(config.cache_dir) or not mkdir(config.temp_dir) \
                or not mkdir(self.file_dir) or not mkdir(self.temp_dir):
            logger.error("Cannot create necessary directories.")
            raise RuntimeError("Cannot create necessary directories.")
        atexit.register(lambda: rmtree(self.temp_dir))

    def load(self, digest, if_needed=False):
        """Load the file with the given digest into the cache.

        Ask the backend to provide the file and, if it's available,
        copy its content into the file-system cache.

        digest (unicode): the digest of the file to load.
        if_needed (bool): only load the file if it is not present in
            the local cache.

        raise (KeyError): if the backend cannot find the file.
        raise (TombstoneError): if the digest is the tombstone

        """
        if digest == FileCacher.TOMBSTONE_DIGEST:
            raise TombstoneError()
        cache_file_path = os.path.join(self.file_dir, digest)
        if if_needed and os.path.exists(cache_file_path):
            return

        ftmp_handle, temp_file_path = tempfile.mkstemp(dir=self.temp_dir,
                                                       text=False)
        with io.open(ftmp_handle, 'wb') as ftmp, \
                self.backend.get_file(digest) as fobj:
            copyfileobj(fobj, ftmp, self.CHUNK_SIZE)

        # Then move it to its real location (this operation is atomic
        # by POSIX requirement)
        os.rename(temp_file_path, cache_file_path)

    def get_file(self, digest):
        """Retrieve a file from the storage.

        If it's available in the cache use that copy, without querying
        the backend. Otherwise ask the backend to provide it, and store
        it in the cache for the benefit of future accesses.

        The file is returned as a file-object. Other interfaces are
        available as `get_file_content', `get_file_to_fobj' and `get_
        file_to_path'.

        digest (unicode): the digest of the file to get.

        return (fileobj): a readable binary file-like object from which
            to read the contents of the file.

        raise (KeyError): if the file cannot be found.
        raise (TombstoneError): if the digest is the tombstone

        """
        if digest == FileCacher.TOMBSTONE_DIGEST:
            raise TombstoneError()
        cache_file_path = os.path.join(self.file_dir, digest)

        logger.debug("Getting file %s.", digest)

        if not os.path.exists(cache_file_path):
            logger.debug("File %s not in cache, downloading "
                         "from database.", digest)

            self.load(digest)

            logger.debug("File %s downloaded.", digest)

        return io.open(cache_file_path, 'rb')

    def get_file_content(self, digest):
        """Retrieve a file from the storage.

        See `get_file'. This method returns the content of the file, as
        a binary string.

        digest (unicode): the digest of the file to get.

        return (bytes): the content of the retrieved file.

        raise (KeyError): if the file cannot be found.
        raise (TombstoneError): if the digest is the tombstone

        """
        if digest == FileCacher.TOMBSTONE_DIGEST:
            raise TombstoneError()
        with self.get_file(digest) as src:
            return src.read()

    def get_file_to_fobj(self, digest, dst):
        """Retrieve a file from the storage.

        See `get_file'. This method will write the content of the file
        to the given file-object.

        digest (unicode): the digest of the file to get.
        dst (fileobj): a writable binary file-like object on which to
            write the contents of the file.

        raise (KeyError): if the file cannot be found.
        raise (TombstoneError): if the digest is the tombstone

        """
        if digest == FileCacher.TOMBSTONE_DIGEST:
            raise TombstoneError()
        with self.get_file(digest) as src:
            copyfileobj(src, dst, self.CHUNK_SIZE)

    def get_file_to_path(self, digest, dst_path):
        """Retrieve a file from the storage.

        See `get_file'. This method will write the content of a file
        to the given file-system location.

        digest (unicode): the digest of the file to get.
        dst_path (string): an accessible location on the file-system on
            which to write the contents of the file.

        raise (KeyError): if the file cannot be found.

        """
        if digest == FileCacher.TOMBSTONE_DIGEST:
            raise TombstoneError()
        with self.get_file(digest) as src:
            with io.open(dst_path, 'wb') as dst:
                copyfileobj(src, dst, self.CHUNK_SIZE)

    def save(self, digest, desc=""):
        """Save the file with the given digest into the backend.

        Use to local copy, available in the file-system cache, to store
        the file in the backend, if it's not already there.

        digest (unicode): the digest of the file to load.
        desc (unicode): the (optional) description to associate to the
            file.

        raise (TombstoneError): if the digest is the tombstone

        """
        if digest == FileCacher.TOMBSTONE_DIGEST:
            raise TombstoneError()
        cache_file_path = os.path.join(self.file_dir, digest)

        fobj = self.backend.create_file(digest)

        if fobj is None:
            return

        with io.open(cache_file_path, 'rb') as src:
            copyfileobj(src, fobj, self.CHUNK_SIZE)

        self.backend.commit_file(fobj, digest, desc)

    def put_file_from_fobj(self, src, desc=""):
        """Store a file in the storage.

        If it's already (for some reason...) in the cache send that
        copy to the backend. Otherwise store it in the file-system
        cache first.

        The file is obtained from a file-object. Other interfaces are
        available as `put_file_content', `put_file_from_path'.

        src (fileobj): a readable binary file-like object from which
            to read the contents of the file.
        desc (unicode): the (optional) description to associate to the
            file.

        return (unicode): the digest of the stored file.

        """
        logger.debug("Reading input file to store on the database.")

        # Unfortunately, we have to read the whole file-obj to compute
        # the digest but we take that chance to save it to a temporary
        # path so that we then just need to move it. Hoping that both
        # locations will be on the same filesystem, that should be way
        # faster than reading the whole file-obj again (as it could be
        # compressed or require network communication).
        # XXX We're *almost* reimplementing copyfileobj.
        with tempfile.NamedTemporaryFile('wb', delete=False,
                                         dir=self.temp_dir) as dst:
            d = Digester()
            buf = src.read(self.CHUNK_SIZE)
            while len(buf) > 0:
                d.update(buf)
                while len(buf) > 0:
                    written = dst.write(buf)
                    # Cooperative yield.
                    gevent.sleep(0)
                    if written is None:
                        break
                    buf = buf[written:]
                buf = src.read(self.CHUNK_SIZE)
            digest = d.digest()
            dst.flush()

            logger.debug("File has digest %s.", digest)

            cache_file_path = os.path.join(self.file_dir, digest)

            if not os.path.exists(cache_file_path):
                os.rename(dst.name, cache_file_path)
            else:
                os.unlink(dst.name)

        # Store the file in the backend. We do that even if the file
        # was already in the cache (that is, we ignore the check above)
        # because there's a (small) chance that the file got removed
        # from the backend but somehow remained in the cache.
        self.save(digest, desc)

        return digest

    def put_file_content(self, content, desc=""):
        """Store a file in the storage.

        See `put_file_from_fobj'. This method will read the content of
        the file from the given binary string.

        content (bytes): the content of the file to store.
        desc (unicode): the (optional) description to associate to the
            file.

        return (unicode): the digest of the stored file.

        """
        with io.BytesIO(content) as src:
            return self.put_file_from_fobj(src, desc)

    def put_file_from_path(self, src_path, desc=""):
        """Store a file in the storage.

        See `put_file_from_fobj'. This method will read the content of
        the file from the given file-system location.

        src_path (string): an accessible location on the file-system
            from which to read the contents of the file.
        desc (unicode): the (optional) description to associate to the
            file.

        return (unicode): the digest of the stored file.

        """
        with io.open(src_path, 'rb') as src:
            return self.put_file_from_fobj(src, desc)

    def describe(self, digest):
        """Return the description of a file given its digest.

        digest (unicode): the digest of the file to describe.

        return (unicode): the description of the file.

        raise (KeyError): if the file cannot be found.

        """
        if digest == FileCacher.TOMBSTONE_DIGEST:
            raise TombstoneError()
        return self.backend.describe(digest)

    def get_size(self, digest):
        """Return the size of a file given its digest.

        digest (unicode): the digest of the file to calculate the size
            of.

        return (int): the size of the file, in bytes.

        raise (KeyError): if the file cannot be found.
        raise (TombstoneError): if the digest is the tombstone

        """
        if digest == FileCacher.TOMBSTONE_DIGEST:
            raise TombstoneError()
        return self.backend.get_size(digest)

    def delete(self, digest):
        """Delete a file from the backend and the local cache.

        digest (unicode): the digest of the file to delete.

        """
        if digest == FileCacher.TOMBSTONE_DIGEST:
            return
        self.drop(digest)
        self.backend.delete(digest)

    def drop(self, digest):
        """Delete a file only from the local cache.

        digest (unicode): the file to delete.

        """
        if digest == FileCacher.TOMBSTONE_DIGEST:
            return
        cache_file_path = os.path.join(self.file_dir, digest)

        try:
            os.unlink(cache_file_path)
        except OSError:
            pass

    def purge_cache(self):
        """Empty the local cache.

        """
        self.destroy_cache()
        if not mkdir(config.cache_dir) or not mkdir(self.file_dir):
            logger.error("Cannot create necessary directories.")
            raise RuntimeError("Cannot create necessary directories.")

    def destroy_cache(self):
        """Completely remove and destroy the cache.

        Nothing that could have been created by this object will be
        left on disk. After that, this instance isn't usable anymore.

        """
        rmtree(self.file_dir)

    def list(self):
        """List the files available in the storage.

        return ([(unicode, unicode)]): a list of pairs, each
            representing a file in the form (digest, description).

        """
        return self.backend.list()

    def check_backend_integrity(self, delete=False):
        """Check the integrity of the backend.

        Request all the files from the backend. For each of them the
        digest is recomputed and checked against the one recorded in
        the backend.

        If mismatches are found, they are reported with ERROR
        severity. The method returns False if at least a mismatch is
        found, True otherwise.

        delete (bool): if True, files with wrong digest are deleted.

        """
        clean = True
        for digest, _ in self.list():
            d = Digester()
            with self.backend.get_file(digest) as fobj:
                buf = fobj.read(self.CHUNK_SIZE)
                while len(buf) > 0:
                    d.update(buf)
                    buf = fobj.read(self.CHUNK_SIZE)
            computed_digest = d.digest()
            if digest != computed_digest:
                logger.error("File with hash %s actually has hash %s",
                             digest, computed_digest)
                if delete:
                    self.delete(digest)
                clean = False

        return clean
