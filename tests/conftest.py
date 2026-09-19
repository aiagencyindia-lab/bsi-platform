import os

_T = "postgresql+psycopg://{u}:{p}@localhost:5433/bsi_test"
os.environ["DATABASE_URL"] = _T.format(u="bsi_app", p="app")
os.environ["OWNER_DATABASE_URL"] = _T.format(u="bsi_owner", p="owner")
os.environ["RAW_STORE_DIR"] = "./data/test"
