"""
Vendor registry — the single place to register all vendor integrations.

To add a new vendor:
  1. Create app/vendors/myvendor.py with a class that subclasses BaseVendor
  2. Import it here and add it to VENDOR_CLASSES
"""
from app.vendors.spectrumxray import SpectrumXrayVendor
from app.vendors.petnet import PetNetVendor

# Map slug -> class. Add new vendors here.
VENDOR_CLASSES: dict = {
    SpectrumXrayVendor.SLUG: SpectrumXrayVendor,
    PetNetVendor.SLUG: PetNetVendor,
}


class VendorRegistry:
    @staticmethod
    def get(slug: str):
        """Return an instantiated vendor handler or None."""
        cls = VENDOR_CLASSES.get(slug)
        return cls() if cls else None

    @staticmethod
    def all_slugs() -> list[str]:
        return list(VENDOR_CLASSES.keys())

    @staticmethod
    def register(vendor_class) -> None:
        """Dynamically register a new vendor at runtime."""
        VENDOR_CLASSES[vendor_class.SLUG] = vendor_class
