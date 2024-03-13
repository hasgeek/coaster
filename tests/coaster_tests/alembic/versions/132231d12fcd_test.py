"""Test Migration.

Revision ID: 132231d12fcd
Revises: None
Create Date: 2013-04-27 11:09:23.896698

"""

from typing import Optional

# revision identifiers, used by Alembic.
revision = '132231d12fcd'
down_revision: Optional[str] = None


def upgrade() -> None:
    """Perform database upgrade."""


def downgrade() -> None:
    """Perform database downgrade."""
