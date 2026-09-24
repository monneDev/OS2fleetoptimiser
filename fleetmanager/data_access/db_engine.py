import os

import sqlalchemy
from sqlalchemy import create_engine, select, inspect, Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from .dbschema import (
    Base,
    FuelTypes,
    LeasingTypes,
    RoundTrips,
    SimulationSettings,
    VehicleTypes,
    get_default_fuel_types,
    get_default_leasing_types,
    get_default_simulation_settings,
    get_default_vehicle_types,
)


def engine_creator(
    db_name=None,
    db_password=None,
    db_user=None,
    db_url=None,
    db_server=None,
) -> sqlalchemy.engine.Engine:
    """
    Generic db engine creator. Loads env variables, e.g. in .env otherwise could be passed with click.
    Ensures that tables according to dbschema is created before returning

    Parameters
    ----------
    db_name
    db_password
    db_user
    db_url

    Returns
    -------
    sqlalchemy.engine
    """
    if db_name is None:
        db_name = os.getenv("DB_NAME")
    if db_password is None:
        db_password = os.getenv("DB_PASSWORD")
    if db_user is None:
        db_user = os.getenv("DB_USER")
    if db_url is None:
        db_url = os.getenv("DB_URL")
    if db_server is None:
        db_server = os.getenv("DB_SERVER")

    database_config = {
        "DB_NAME": db_name,
        "DB_PASSWORD": db_password,
        "DB_USER": db_user,
        "DB_URL": db_url,
        "DB_SERVER": db_server,
    }
    configured_values = [value for value in database_config.values() if value]

    if len(configured_values) == len(database_config):
        dsn = f"{db_server}://{db_user}:{db_password}@{db_url}/{db_name}"
        if db_server == "mssql+pyodbc":
            dsn += "?driver=ODBC+Driver+18+for+SQL+Server"

        pool_size = int(os.getenv("DB_POOL_SIZE", "5"))
        max_overflow = int(os.getenv("DB_MAX_OVERFLOW", "10"))
        pool_timeout = int(os.getenv("DB_POOL_TIMEOUT", "30"))
        pool_pre_ping = os.getenv("DB_POOL_PRE_PING", "false").lower() == "true"

        db_engine = create_engine(
            dsn,
            pool_recycle=1800,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=pool_timeout,
            pool_pre_ping=pool_pre_ping,
            # encoding="latin-1",
        )
    elif configured_values:
        missing = ", ".join(
            name for name, value in database_config.items() if not value
        )
        raise RuntimeError(
            f"Incomplete database configuration. Missing: {missing}. "
            "Set all DB_* variables."
        )
    elif os.getenv("ALLOW_IN_MEMORY_DATABASE", "false").lower() == "true":
        db_engine = create_engine(
            "sqlite:///file:fleetdb?mode=memory&cache=shared&uri=true",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            # encoding="latin-1",
        )
    else:
        raise RuntimeError(
            "Database configuration is required. Set DB_SERVER, DB_URL, DB_NAME, "
            "DB_USER and DB_PASSWORD. In-memory SQLite can only be enabled "
            "explicitly with ALLOW_IN_MEMORY_DATABASE=true for local development "
            "or tests."
        )

    insp = inspect(db_engine)

    if not insp.has_table("cars"):
        Base.metadata.create_all(db_engine)
        create_defaults(db_engine)

    # create_all above only runs on a fresh database, so create the workshop
    # tables and their default setting on already-populated databases too
    if not insp.has_table("workshops") or not insp.has_table("workshop_visits"):
        Base.metadata.create_all(db_engine)
        ensure_workshop_defaults(db_engine)

    return db_engine


def ensure_workshop_defaults(engine_: Engine) -> None:
    """
    Seed the workshop default settings on databases created before the feature.
    """
    from .dbschema import get_default_simulation_settings

    Session = sessionmaker(bind=engine_)
    with Session.begin() as sess:
        for setting in get_default_simulation_settings():
            if setting.name != "workshop_visit_min_hours":
                continue
            existing = sess.execute(
                select(SimulationSettings).where(
                    SimulationSettings.name == setting.name
                )
            ).all()
            if len(existing) == 0:
                sess.add(setting)


def create_defaults(engine_: Engine) -> None:
    """
    Function to load in the defaults defined in dbschema
    """
    Session = sessionmaker(bind=engine_)
    with Session.begin() as sess:
        for vehicle_type in get_default_vehicle_types():
            if (
                len(
                    sess.execute(
                        select(VehicleTypes).where(VehicleTypes.id == vehicle_type.id)
                    ).all()
                )
                == 0
            ):
                sess.add(vehicle_type)

        for leasing_type in get_default_leasing_types():
            if (
                len(
                    sess.execute(
                        select(LeasingTypes).where(LeasingTypes.id == leasing_type.id)
                    ).all()
                )
                == 0
            ):
                sess.add(leasing_type)

        for fuel_type in get_default_fuel_types():
            if (
                len(
                    sess.execute(
                        select(FuelTypes).where(FuelTypes.id == fuel_type.id)
                    ).all()
                )
                == 0
            ):
                sess.add(fuel_type)

        for setting in get_default_simulation_settings():
            if (
                len(
                    sess.execute(
                        select(SimulationSettings).where(
                            SimulationSettings.id == setting.id
                        )
                    ).all()
                )
                == 0
            ):
                sess.add(setting)
