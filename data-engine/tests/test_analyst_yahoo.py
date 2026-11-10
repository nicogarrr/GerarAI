"""analyst_yahoo: fetch_upgrades_downgrades_records mapea el superset de campos."""

import pandas as pd

from app.services import analyst_yahoo


class _TickerFalso:
    def __init__(self, frame):
        self.upgrades_downgrades = frame


def test_mapea_superset_de_campos() -> None:
    ud = pd.DataFrame(
        {
            "Firm": ["Acme"],
            "ToGrade": ["Overweight"],
            "FromGrade": ["Equal Weight"],
            "Action": ["up"],
            "priceTargetAction": ["raises"],
            "currentPriceTarget": [500.0],
            "priorPriceTarget": [450.0],
        },
        index=pd.DatetimeIndex([pd.Timestamp("2022-05-01 12:00")], name="GradeDate"),
    )
    records = analyst_yahoo.fetch_upgrades_downgrades_records(_TickerFalso(ud))
    assert records == [
        {
            "date": pd.Timestamp("2022-05-01 12:00"),
            "firm": "Acme",
            "to_grade": "Overweight",
            "from_grade": "Equal Weight",
            "action": "up",
            "price_target_action": "raises",
            "price_target": 500.0,
            "prior_target": 450.0,
        }
    ]


def test_frame_vacio_devuelve_lista_vacia() -> None:
    assert analyst_yahoo.fetch_upgrades_downgrades_records(_TickerFalso(None)) == []
