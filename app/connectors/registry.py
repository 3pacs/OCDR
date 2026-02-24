"""
Connector registry — maps slug → connector class.

To add a new connector:
  1. Create app/connectors/mysite.py subclassing BaseConnector
  2. Import it here and add to CONNECTOR_CLASSES
"""
from app.connectors.officeally import OfficeAllyConnector
from app.connectors.optumpay import OptumPayConnector
from app.connectors.changehealth import ChangeHealthConnector
from app.connectors.spectrumxray_web import SpectrumXrayWebConnector
from app.connectors.candalis import CandalisConnector
from app.connectors.purview import PurviewConnector

CONNECTOR_CLASSES: dict = {
    OfficeAllyConnector.SLUG: OfficeAllyConnector,
    OptumPayConnector.SLUG: OptumPayConnector,
    ChangeHealthConnector.SLUG: ChangeHealthConnector,
    SpectrumXrayWebConnector.SLUG: SpectrumXrayWebConnector,
    CandalisConnector.SLUG: CandalisConnector,
    PurviewConnector.SLUG: PurviewConnector,
}

# Metadata shown in the UI for connectors without saved credentials
CONNECTOR_META = {
    slug: {
        "slug": slug,
        "display_name": cls.DISPLAY_NAME,
        "base_url": cls.BASE_URL,
    }
    for slug, cls in CONNECTOR_CLASSES.items()
}


class ConnectorRegistry:
    @staticmethod
    def get(slug: str) -> "BaseConnector | None":
        cls = CONNECTOR_CLASSES.get(slug)
        return cls() if cls else None

    @staticmethod
    def all_slugs() -> list[str]:
        return list(CONNECTOR_CLASSES.keys())

    @staticmethod
    def meta() -> list[dict]:
        return list(CONNECTOR_META.values())

    @staticmethod
    def register(connector_class) -> None:
        """Dynamically register a new connector at runtime."""
        CONNECTOR_CLASSES[connector_class.SLUG] = connector_class
        CONNECTOR_META[connector_class.SLUG] = {
            "slug": connector_class.SLUG,
            "display_name": connector_class.DISPLAY_NAME,
            "base_url": connector_class.BASE_URL,
        }
