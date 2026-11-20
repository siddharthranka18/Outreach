from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine,inspect,text

def test_tracking_migration_upgrade_and_downgrade_preserves_existing_rows(tmp_path):
    root=Path(__file__).resolve().parents[1]
    config=Config(str(root/'alembic.ini'))
    config.set_main_option('script_location',str(root/'alembic'))
    url='sqlite:///'+str(tmp_path/'migration.db').replace('\\','/')
    config.set_main_option('sqlalchemy.url',url)
    command.upgrade(config,'2ba211d53e01')
    engine=create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO companies (company_name,normalized_name,website,normalized_website,source_name,source_url,created_at,updated_at) VALUES ('Studio','studio','https://studio.example','studio.example','test','https://studio.example',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
    command.upgrade(config,'head')
    assert 'ats_boards' in {c['name'] for c in inspect(engine).get_columns('companies')}
    assert 'missing_ats_polls' in {c['name'] for c in inspect(engine).get_columns('jobs')}
    command.downgrade(config,'2ba211d53e01')
    assert 'ats_boards' not in {c['name'] for c in inspect(engine).get_columns('companies')}
    with engine.connect() as conn:assert conn.execute(text('SELECT company_name FROM companies')).scalar()=='Studio'
    engine.dispose()
