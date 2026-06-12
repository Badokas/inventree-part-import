import importlib
from inspect import isclass
from multiprocessing.pool import ThreadPool
from pathlib import Path
from typing import Any

from error_helper import error, hint
from inventree.api import InvenTreeAPI
from inventree.company import Company as InvenTreeCompany

from ..config import SUPPLIERS_CONFIG, get_config, load_suppliers_config, update_config_file
from ..inventree_helpers import Company
from .base import ScrapeSupplier, Supplier

_suppliers = None


def search(
    search_term: str,
    supplier_id: str | None = None,
    only_supplier: bool = False,
    supplier_overrides: dict[str, str] | None = None,
):
    global _suppliers
    if _suppliers is None:
        assert _supplier_companies is not None, "call setup_supplier_companies(...) first"
        supplier_objects, _ = get_suppliers()
        assert supplier_objects.keys() == _supplier_companies.keys()
        _suppliers = dict(
            zip(
                supplier_objects.keys(),
                zip(supplier_objects.values(), _supplier_companies.values()),
            )
        )

    suppliers = list(_suppliers.items())
    if supplier_id:
        if supplier_id in _suppliers:
            if only_supplier:
                suppliers = [(supplier_id, _suppliers[supplier_id])]
            else:
                entry = (supplier_id, _suppliers[supplier_id])
                suppliers.remove(entry)
                suppliers.insert(0, entry)
        else:
            error(f"supplier id '{supplier_id}' not defined in {SUPPLIERS_CONFIG}")
            return None

    thread_pool = ThreadPool(processes=8)
    return (
        (
            api_company,
            thread_pool.apply_async(
                supplier_object.cached_search,
                # Use the supplier-specific override term if provided, else the default term
                (supplier_overrides.get(sid, search_term) if supplier_overrides else search_term,),
            ),
        )
        for sid, (supplier_object, api_company) in suppliers
        # Skip suppliers that have no relevant term (empty override + no MPN)
        if (supplier_overrides.get(sid, search_term) if supplier_overrides else search_term)
    )


_supplier_companies: dict[str, InvenTreeCompany] | None = None


def setup_supplier_companies(inventree_api: InvenTreeAPI):
    global _supplier_companies
    _supplier_companies = {}
    global_config = get_config()

    with update_config_file(SUPPLIERS_CONFIG) as suppliers_config:
        assert _supplier_objects is not None
        for id, supplier_object in _supplier_objects.items():
            supplier_config: dict[str, Any] | None = suppliers_config.get(id)
            if supplier_config is None:
                supplier_config = suppliers_config[id] = {}
            api_company = Company(
                name=supplier_object.name,
                currency=supplier_config.get("currency", global_config["currency"]),
                is_supplier=True,
                primary_key=supplier_config.get("_primary_key"),
            ).setup(inventree_api)
            if not hasattr(inventree_api, "DRY_RUN"):
                supplier_config["_primary_key"] = api_company.pk
            _supplier_companies[id] = api_company


_supplier_objects: dict[str, Supplier] | None = None
_available_supplier_objects: dict[str, Supplier] | None = None


def get_suppliers(reload: bool = False, setup: bool = True):
    global _supplier_objects, _available_supplier_objects
    if not reload and _supplier_objects is not None and _available_supplier_objects is not None:
        return _supplier_objects, _available_supplier_objects

    _supplier_objects = {}
    _available_supplier_objects = {}
    for path in Path(__file__).parent.glob("supplier_*.py"):
        module_name = path.stem
        try:
            if module_name in locals():
                module = importlib.reload(locals()[module_name])
            else:
                module = importlib.import_module(f".{module_name}", package=__package__)
        except ImportError as e:
            error(f"failed to load supplier module '{module_name}' with {e}")
            continue

        supplier_classes = [
            cls
            for cls in vars(module).values()
            if isclass(cls) and cls not in (Supplier, ScrapeSupplier) and issubclass(cls, Supplier)
        ]
        if len(supplier_classes) != 1:
            suffix = "multiple Supplier classes" if supplier_classes else "no Supplier class"
            error(f"failed to load supplier module '{module_name}' ({suffix} defined)")
            continue

        if not hasattr(supplier_classes[0], "SUPPORT_LEVEL"):
            error(f"failed to load supplier module '{module_name}' (undefined SUPPORT_LEVEL)")
            continue

        id = module_name.split("supplier_", 1)[-1]
        _available_supplier_objects[id] = supplier_classes[0]()

    _available_supplier_objects = dict(
        sorted(
            _available_supplier_objects.items(),
            key=lambda supplier_item: (supplier_item[1].SUPPORT_LEVEL, supplier_item[1].name),
        )
    )

    _supplier_objects = load_suppliers_config(_available_supplier_objects, setup=setup)

    if (available := len(_available_supplier_objects)) > (loaded := len(_supplier_objects)):
        if setup:
            hint(f"only {loaded} of {available} available supplier modules are configured")

    return _supplier_objects, _available_supplier_objects
