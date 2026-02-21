"""Governance, Code Bindings, and lifecycle columns

Revision ID: 20260220
Revises: 20250617
Create Date: 2026-02-20 19:00:00.000000

Adds:
- context_scopes table (Feature 1)
- governance_rules table (Feature 1)
- scope_amendments table (Feature 1)
- code_bindings table (Feature 2)
- code_binding_verifications table (Feature 2)
- scope_id, visibility, override_status, lifecycle_status columns to existing tables
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20260220'
down_revision = '20250617'
branch_labels = None
depends_on = None


def _column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column already exists in a table (for idempotent migrations)."""
    bind = op.get_bind()
    result = bind.execute(
        sa.text(f"PRAGMA table_info({table_name})")
    )
    columns = [row[1] for row in result]
    return column_name in columns


def _table_exists(table_name: str) -> bool:
    """Check if a table already exists."""
    bind = op.get_bind()
    result = bind.execute(
        sa.text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=:name"
        ),
        {"name": table_name}
    )
    return result.fetchone() is not None


def upgrade() -> None:
    # =============================================
    # FEATURE 1: Team/Individual Context Governance
    # =============================================

    # --- context_scopes ---
    if not _table_exists('context_scopes'):
        op.create_table(
            'context_scopes',
            sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
            sa.Column('scope_type', sa.Text(), nullable=False),  # 'team' or 'individual'
            sa.Column('scope_name', sa.Text(), nullable=False),
            sa.Column('parent_scope_id', sa.Integer(), nullable=True),
            sa.Column('created_by', sa.Text(), nullable=False),
            sa.Column('created_at', sa.DateTime(),
                       server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
            sa.ForeignKeyConstraint(['parent_scope_id'], ['context_scopes.id'],
                                     ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('ix_context_scopes_scope_type', 'context_scopes', ['scope_type'])
        op.create_index('ix_context_scopes_parent_scope_id', 'context_scopes', ['parent_scope_id'])

    # --- governance_rules ---
    if not _table_exists('governance_rules'):
        op.create_table(
            'governance_rules',
            sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
            sa.Column('scope_id', sa.Integer(), nullable=False),
            sa.Column('rule_type', sa.Text(), nullable=False),  # 'hard_block', 'soft_warn', 'allow_with_flag'
            sa.Column('entity_type', sa.Text(), nullable=False),  # e.g., 'decision', 'system_pattern'
            sa.Column('rule_definition', sa.Text(), nullable=False),  # JSON
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('1')),
            sa.Column('created_at', sa.DateTime(),
                       server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
            sa.Column('updated_at', sa.DateTime(),
                       server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
            sa.ForeignKeyConstraint(['scope_id'], ['context_scopes.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('ix_governance_rules_scope_id', 'governance_rules', ['scope_id'])
        op.create_index('ix_governance_rules_entity_type', 'governance_rules', ['entity_type'])
        op.create_index('ix_governance_rules_is_active', 'governance_rules', ['is_active'])

    # --- scope_amendments ---
    if not _table_exists('scope_amendments'):
        op.create_table(
            'scope_amendments',
            sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
            sa.Column('source_item_type', sa.Text(), nullable=False),
            sa.Column('source_item_id', sa.Integer(), nullable=False),
            sa.Column('target_item_type', sa.Text(), nullable=False),
            sa.Column('target_item_id', sa.Integer(), nullable=False),
            sa.Column('status', sa.Text(), nullable=False),  # 'proposed', 'under_review', 'accepted', 'rejected'
            sa.Column('rationale', sa.Text(), nullable=True),
            sa.Column('reviewed_by', sa.Text(), nullable=True),
            sa.Column('reviewed_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(),
                       server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('ix_scope_amendments_status', 'scope_amendments', ['status'])

    # --- Add governance columns to decisions ---
    if not _column_exists('decisions', 'scope_id'):
        op.add_column('decisions',
                       sa.Column('scope_id', sa.Integer(), nullable=True))
    if not _column_exists('decisions', 'visibility'):
        op.add_column('decisions',
                       sa.Column('visibility', sa.Text(),
                                  server_default=sa.text("'workspace'"), nullable=True))
    if not _column_exists('decisions', 'override_status'):
        op.add_column('decisions',
                       sa.Column('override_status', sa.Text(), nullable=True))
    if not _column_exists('decisions', 'lifecycle_status'):
        op.add_column('decisions',
                       sa.Column('lifecycle_status', sa.Text(),
                                  server_default=sa.text("'accepted'"), nullable=True))

    # --- Add governance columns to system_patterns ---
    if not _column_exists('system_patterns', 'scope_id'):
        op.add_column('system_patterns',
                       sa.Column('scope_id', sa.Integer(), nullable=True))
    if not _column_exists('system_patterns', 'visibility'):
        op.add_column('system_patterns',
                       sa.Column('visibility', sa.Text(),
                                  server_default=sa.text("'workspace'"), nullable=True))
    if not _column_exists('system_patterns', 'override_status'):
        op.add_column('system_patterns',
                       sa.Column('override_status', sa.Text(), nullable=True))

    # --- Add governance columns to progress_entries ---
    if not _column_exists('progress_entries', 'scope_id'):
        op.add_column('progress_entries',
                       sa.Column('scope_id', sa.Integer(), nullable=True))
    if not _column_exists('progress_entries', 'visibility'):
        op.add_column('progress_entries',
                       sa.Column('visibility', sa.Text(),
                                  server_default=sa.text("'workspace'"), nullable=True))
    if not _column_exists('progress_entries', 'override_status'):
        op.add_column('progress_entries',
                       sa.Column('override_status', sa.Text(), nullable=True))

    # --- Add governance columns to custom_data ---
    if not _column_exists('custom_data', 'scope_id'):
        op.add_column('custom_data',
                       sa.Column('scope_id', sa.Integer(), nullable=True))
    if not _column_exists('custom_data', 'visibility'):
        op.add_column('custom_data',
                       sa.Column('visibility', sa.Text(),
                                  server_default=sa.text("'workspace'"), nullable=True))
    if not _column_exists('custom_data', 'override_status'):
        op.add_column('custom_data',
                       sa.Column('override_status', sa.Text(), nullable=True))

    # =============================================
    # FEATURE 2: Codebase-Context Bridging
    # =============================================

    # --- code_bindings ---
    if not _table_exists('code_bindings'):
        op.create_table(
            'code_bindings',
            sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
            sa.Column('item_type', sa.Text(), nullable=False),
            sa.Column('item_id', sa.Integer(), nullable=False),
            sa.Column('file_pattern', sa.Text(), nullable=False),
            sa.Column('symbol_pattern', sa.Text(), nullable=True),
            sa.Column('binding_type', sa.Text(), nullable=False),  # 'implements', 'governed_by', etc.
            sa.Column('confidence', sa.Text(),
                       server_default=sa.text("'manual'"), nullable=False),
            sa.Column('last_verified_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(),
                       server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
            sa.Column('updated_at', sa.DateTime(),
                       server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('ix_code_bindings_item_type', 'code_bindings', ['item_type'])
        op.create_index('ix_code_bindings_item_id', 'code_bindings', ['item_id'])
        op.create_index('ix_code_bindings_item_type_id', 'code_bindings',
                         ['item_type', 'item_id'])
        op.create_index('ix_code_bindings_binding_type', 'code_bindings', ['binding_type'])

    # --- code_binding_verifications ---
    if not _table_exists('code_binding_verifications'):
        op.create_table(
            'code_binding_verifications',
            sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
            sa.Column('binding_id', sa.Integer(), nullable=False),
            sa.Column('verification_status', sa.Text(), nullable=False),
            sa.Column('files_matched', sa.Integer(), nullable=True),
            sa.Column('verified_at', sa.DateTime(),
                       server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(['binding_id'], ['code_bindings.id'],
                                     ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('ix_code_binding_verifications_binding_id',
                         'code_binding_verifications', ['binding_id'])


def downgrade() -> None:
    # Feature 2 tables
    op.drop_table('code_binding_verifications')
    op.drop_table('code_bindings')

    # Feature 1 columns from existing tables
    # SQLite doesn't support DROP COLUMN in older versions; these are best-effort
    try:
        op.drop_column('custom_data', 'override_status')
        op.drop_column('custom_data', 'visibility')
        op.drop_column('custom_data', 'scope_id')

        op.drop_column('progress_entries', 'override_status')
        op.drop_column('progress_entries', 'visibility')
        op.drop_column('progress_entries', 'scope_id')

        op.drop_column('system_patterns', 'override_status')
        op.drop_column('system_patterns', 'visibility')
        op.drop_column('system_patterns', 'scope_id')

        op.drop_column('decisions', 'lifecycle_status')
        op.drop_column('decisions', 'override_status')
        op.drop_column('decisions', 'visibility')
        op.drop_column('decisions', 'scope_id')
    except Exception:
        pass  # SQLite limitation

    # Feature 1 tables
    op.drop_table('scope_amendments')
    op.drop_table('governance_rules')
    op.drop_table('context_scopes')
