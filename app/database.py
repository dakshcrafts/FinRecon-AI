import logging
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from app.config import settings

logger = logging.getLogger("finrecon.database")

# SQLite configuration
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {},
    echo=False
)

# Enable SQLite foreign key constraints and WAL mode
if "sqlite" in settings.DATABASE_URL:
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    """Initialize database tables and create default admin account if not existing."""
    from app.models.user import User, UserRole
    from app.models.invoice import Invoice
    from app.models.payment import Payment
    from app.models.reconciliation import ReconciliationMatch, ReconciliationSetting
    from app.models.audit import AuditLog
    from app.models.anomaly import AnomalyRecord
    from app.services.auth_service import hash_password

    Base.metadata.create_all(bind=engine)
    logger.info("Database tables initialized successfully.")

    # Safe lightweight schema migrations for existing SQLite databases
    if "sqlite" in settings.DATABASE_URL:
        try:
            with engine.connect() as conn:
                cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(reconciliation_settings)").fetchall()]
                if "ambiguity_margin" not in cols:
                    conn.exec_driver_sql("ALTER TABLE reconciliation_settings ADD COLUMN ambiguity_margin FLOAT DEFAULT 5.0")
                    logger.info("Migrated schema: Added ambiguity_margin column to reconciliation_settings.")
        except Exception as mig_err:
            logger.warning(f"Schema migration notice: {mig_err}")

    db: Session = SessionLocal()
    try:
        # Check admin user
        admin = db.query(User).filter(User.email == settings.ADMIN_EMAIL).first()
        if not admin:
            admin_user = User(
                email=settings.ADMIN_EMAIL,
                hashed_password=hash_password(settings.ADMIN_PASSWORD),
                full_name=settings.ADMIN_NAME,
                role=UserRole.ADMIN,
                is_active=True
            )
            db.add(admin_user)
            db.commit()
            logger.info(f"Default admin user created: {settings.ADMIN_EMAIL}")

        # Check default reconciliation settings
        setting = db.query(ReconciliationSetting).first()
        if not setting:
            default_setting = ReconciliationSetting(
                weight_invoice_number=settings.WEIGHT_INVOICE_NUMBER,
                weight_customer_name=settings.WEIGHT_CUSTOMER_NAME,
                weight_amount=settings.WEIGHT_AMOUNT,
                weight_date_proximity=settings.WEIGHT_DATE_PROXIMITY,
                auto_match_threshold=settings.AUTO_MATCH_THRESHOLD,
                review_queue_threshold=settings.REVIEW_QUEUE_THRESHOLD,
                auto_match_enabled=True,
                date_tolerance_days=30
            )
            db.add(default_setting)
            db.commit()
            logger.info("Default reconciliation settings initialized.")
    except Exception as e:
        db.rollback()
        logger.error(f"Error during init_db: {e}")
        raise
    finally:
        db.close()

def backup_database(destination_dir: str = None) -> str:
    """Create a timestamped backup of the current SQLite database safely."""
    import shutil
    from datetime import datetime
    from pathlib import Path
    
    db_path = settings.DATA_DIR / "finrecon.db"
    if not db_path.exists():
        # Check base dir fallback
        db_path = settings.BASE_DIR / "finrecon.db"
    
    if not db_path.exists():
        raise FileNotFoundError(f"Database file not found at {db_path}")

    backup_folder = Path(destination_dir) if destination_dir else (settings.DATA_DIR / "backups")
    backup_folder.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target_path = backup_folder / f"finrecon_backup_{timestamp}.db"
    
    # Flush SQLite WAL to disk safely if active
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception as e:
        logger.warning(f"WAL checkpoint warning: {e}")

    shutil.copy2(db_path, target_path)
    logger.info(f"Database backed up successfully to {target_path}")
    return str(target_path)

