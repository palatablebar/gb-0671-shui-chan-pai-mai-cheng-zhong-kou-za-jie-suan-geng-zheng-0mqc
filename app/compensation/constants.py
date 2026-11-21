import os
COMP_RULE_VERSION = '2026.11.21-margin-r1'
COMP_TABLES = ('tickets', 'refunds', 'deposits')
MAX_BYTES = 2_000_000
DB_PATH = os.environ.get('COMP_DB_PATH', os.environ.get('DB_PATH', '/data/workbench.sqlite'))
