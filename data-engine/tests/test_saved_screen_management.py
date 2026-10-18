import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.screeners import (
    ScreenCreate,
    delete_screen,
    list_screens,
    run_saved_screen,
    update_screen,
)
from app.core.database import Base
from app.models import SavedScreen, Tenant


def test_edit_archive_preserves_record_and_disables_run():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Tenant(id=1, external_id='screen-management'))
        db.flush()
        db.info['tenant_id'] = 1
        screen = SavedScreen(name='Test', criteria=[{'left':'market_cap','operator':'>','right':'100'}])
        db.add(screen)
        db.commit()
        payload = ScreenCreate(name='Renamed', criteria=[{'left':'market_cap','operator':'>','right':'200'}], alerts_enabled=False)
        assert update_screen(screen.id, payload, db)['name'] == 'Renamed'
        assert list_screens(db)[0]['criteria'][0]['right'] == '200'
        assert delete_screen(screen.id, db)['status'] == 'archived'
        assert list_screens(db) == []
        assert db.get(SavedScreen, screen.id) is not None
        assert screen.alerts_enabled is False
        with pytest.raises(HTTPException) as error:
            run_saved_screen(screen.id, db)
        assert error.value.status_code == 404
