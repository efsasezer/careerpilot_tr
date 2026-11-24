"""Testler gerçek careerpilot.db dosyasına dokunmaz; geçici bir veritabanı kullanır."""

import os
import tempfile
from pathlib import Path

_TEST_DIR = Path(tempfile.mkdtemp(prefix="careerpilot-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DIR / 'test.db'}"
os.environ["CAREERPILOT_DB_AUTOCREATE"] = "true"
os.environ["CAREERPILOT_DISABLE_SCHEDULER"] = "true"
os.environ["CAREERPILOT_SOURCE_REQUEST_DELAY_SECONDS"] = "0"
os.environ["CAREERPILOT_DISABLE_RESULT_CHECK"] = "true"
