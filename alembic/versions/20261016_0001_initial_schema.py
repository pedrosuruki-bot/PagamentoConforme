"""Initial PagamentoConforme schema."""
from alembic import op
from app.db import Base
import app.models

revision = "20261016_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
