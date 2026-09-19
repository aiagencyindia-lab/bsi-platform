from alembic import context
from bsi_core.config import get_settings
from bsi_core.models import Base
from sqlalchemy import create_engine

engine = create_engine(get_settings().owner_database_url)
with engine.connect() as conn:
    context.configure(connection=conn, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
