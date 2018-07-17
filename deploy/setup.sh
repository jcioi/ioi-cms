#!/bin/bash
set -xe
cd /opt/cms

chmod +x ./cmscontrib/AddAdmin.py
chmod +x ./cmscontrib/AddParticipation.py
chmod +x ./cmscontrib/AddStatement.py
chmod +x ./cmscontrib/AddSubmission.py
chmod +x ./cmscontrib/AddTeam.py
chmod +x ./cmscontrib/AddTestcases.py
chmod +x ./cmscontrib/AddUser.py
chmod +x ./cmscontrib/check_cache.sh
chmod +x ./cmscontrib/CleanFiles.py
chmod +x ./cmscontrib/DumpExporter.py
chmod +x ./cmscontrib/DumpImporter.py
chmod +x ./cmscontrib/DumpUpdater.py
chmod +x ./cmscontrib/ExportSubmissions.py
chmod +x ./cmscontrib/ImportContest.py
chmod +x ./cmscontrib/ImportDataset.py
chmod +x ./cmscontrib/ImportTask.py
chmod +x ./cmscontrib/ImportTeam.py
chmod +x ./cmscontrib/ImportUser.py
chmod +x ./cmscontrib/RemoveContest.py
chmod +x ./cmscontrib/RemoveParticipation.py
chmod +x ./cmscontrib/RemoveSubmissions.py
chmod +x ./cmscontrib/RemoveTask.py
chmod +x ./cmscontrib/RemoveUser.py
chmod +x ./cmscontrib/setup_fs_storage.sh
chmod +x ./cmscontrib/SpoolExporter.py
chmod +x ./cmsranking/RankingWebServer.py
chmod +x ./cmstaskenv/cmsMake.py
chmod +x ./prerequisites.py
chmod +x ./scripts/cmsAdminWebServer
chmod +x ./scripts/cmsChecker
chmod +x ./scripts/cmsContestWebServer
chmod +x ./scripts/cmsDropDB
chmod +x ./scripts/cmsEvaluationService
chmod +x ./scripts/cmsInitDB
chmod +x ./scripts/cmsLogService
chmod +x ./scripts/cmsPrintingService
chmod +x ./scripts/cmsProxyService
chmod +x ./scripts/cmsRankingWebServer
chmod +x ./scripts/cmsResourceService
chmod +x ./scripts/cmsScoringService
chmod +x ./scripts/cmsWorker
chmod +x ./setup.py

if [ ! -e /opt/cms_venv/.built-on-codebuild  ];then
  ./deploy/install-deps.sh
fi
