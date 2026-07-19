"""SQLAlchemy data models."""

from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(AsyncAttrs, DeclarativeBase):
    pass


class Vendor(Base):
    __tablename__ = "vendor"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    registered: Mapped[datetime] = mapped_column()
    name: Mapped[str] = mapped_column(String(64))
    empty_spool_weight: Mapped[float | None] = mapped_column(comment="The weight of an empty spool.")
    comment: Mapped[str | None] = mapped_column(String(1024))
    filaments: Mapped[list["Filament"]] = relationship(back_populates="vendor")
    external_id: Mapped[str | None] = mapped_column(String(256))
    extra: Mapped[list["VendorField"]] = relationship(
        back_populates="vendor",
        cascade="save-update, merge, delete, delete-orphan",
        lazy="joined",
    )


class Shop(Base):
    """A shop where filament is (re)ordered (#298). Distinct from Vendor (the manufacturer).

    ``ships_to`` is a comma-separated list of free-form region strings (e.g. ``"CH,EU,DE"``), stored
    in a Text column because the schema has no JSON/list columns; it is serialized to/from a JSON
    array at the API edge. ``name`` is unique so inline shop autocomplete can dedupe.
    """

    __tablename__ = "shop"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    registered: Mapped[datetime] = mapped_column()
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    homepage: Mapped[str | None] = mapped_column(String(1024))
    ships_to: Mapped[str | None] = mapped_column(
        Text(),
        comment="Comma-separated free-form region codes this shop ships to (e.g. 'CH,EU,DE'). "
        "Serialized to/from a JSON array at the API edge. Null means unspecified.",
    )
    comment: Mapped[str | None] = mapped_column(String(1024))
    orders: Mapped[list["Order"]] = relationship(back_populates="shop")


class Order(Base):
    """A grouped (bulk) reorder (#298).

    Table name ``purchase_order`` because ``order`` is a reserved SQL word (ORDER BY) in
    PostgreSQL/MySQL/CockroachDB — same reasoning as User -> ``user_account`` (#52). State
    (open/arrived) is DERIVED from the lines, never stored: open while any line is un-arrived.
    """

    __tablename__ = "purchase_order"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    registered: Mapped[datetime] = mapped_column()
    shop_id: Mapped[int | None] = mapped_column(ForeignKey("shop.id"))
    shop: Mapped[Optional["Shop"]] = relationship(back_populates="orders")
    ordered_at: Mapped[datetime] = mapped_column(comment="When the order was placed. Defaults to creation time.")
    order_number: Mapped[str | None] = mapped_column(String(256))
    url: Mapped[str | None] = mapped_column(String(1024))
    comment: Mapped[str | None] = mapped_column(String(1024))
    lines: Mapped[list["OrderLine"]] = relationship(
        back_populates="order",
        cascade="save-update, merge, delete, delete-orphan",
        lazy="joined",
    )


class OrderLine(Base):
    """One filament line within an Order (#298).

    Arrival is tracked PER LINE (``arrived_at``) to support split shipments. No unique constraint on
    (order_id, filament_id): the same filament may appear twice — including as the arrived and
    still-outstanding halves of a split line. The filament FK has no cascade so deleting a filament
    referenced by a line is restricted (enforced in the application layer; see filament.delete).
    """

    __tablename__ = "order_line"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("purchase_order.id", ondelete="CASCADE"), index=True)
    order: Mapped["Order"] = relationship(back_populates="lines")
    filament_id: Mapped[int] = mapped_column(ForeignKey("filament.id"))
    filament: Mapped["Filament"] = relationship()
    quantity: Mapped[int] = mapped_column(comment="Number of spools ordered on this line. Always >= 1.")
    price_per_unit: Mapped[float | None] = mapped_column()
    arrived_at: Mapped[datetime | None] = mapped_column(
        comment="When this line arrived (#298). Null means still outstanding; per-line to support split shipments.",
    )


class Filament(Base):
    __tablename__ = "filament"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    registered: Mapped[datetime] = mapped_column()
    name: Mapped[str | None] = mapped_column(String(64))
    vendor_id: Mapped[int | None] = mapped_column(ForeignKey("vendor.id"))
    vendor: Mapped[Optional["Vendor"]] = relationship(back_populates="filaments")
    spools: Mapped[list["Spool"]] = relationship(back_populates="filament")
    material: Mapped[str | None] = mapped_column(String(64))
    price: Mapped[float | None] = mapped_column()
    density: Mapped[float] = mapped_column()
    diameter: Mapped[float] = mapped_column()
    weight: Mapped[float | None] = mapped_column(comment="The filament weight of a full spool (net weight).")
    spool_weight: Mapped[float | None] = mapped_column(comment="The weight of an empty spool.")
    article_number: Mapped[str | None] = mapped_column(String(64))
    comment: Mapped[str | None] = mapped_column(String(1024))
    settings_extruder_temp: Mapped[int | None] = mapped_column(comment="Overridden extruder temperature.")
    settings_bed_temp: Mapped[int | None] = mapped_column(comment="Overridden bed temperature.")
    settings_extruder_temp_min: Mapped[int | None] = mapped_column(
        comment="Low end of the recommended extruder temperature range, in °C (#112). Null if no range.",
    )
    settings_extruder_temp_max: Mapped[int | None] = mapped_column(
        comment="High end of the recommended extruder temperature range, in °C (#112). Null if no range.",
    )
    settings_bed_temp_min: Mapped[int | None] = mapped_column(
        comment="Low end of the recommended bed temperature range, in °C (#112). Null if no range.",
    )
    settings_bed_temp_max: Mapped[int | None] = mapped_column(
        comment="High end of the recommended bed temperature range, in °C (#112). Null if no range.",
    )
    # SpoolmanDB catalog descriptors, preserved on local import (#91 / #567). Null means unknown.
    spool_type: Mapped[str | None] = mapped_column(String(16), comment="Spool material, e.g. plastic/cardboard/metal.")
    finish: Mapped[str | None] = mapped_column(String(16), comment="Surface finish, e.g. matte/glossy.")
    pattern: Mapped[str | None] = mapped_column(String(16), comment="Visual pattern, e.g. marble/sparkle.")
    translucent: Mapped[bool | None] = mapped_column(comment="Whether the filament is translucent. Null if unknown.")
    glow: Mapped[bool | None] = mapped_column(comment="Whether the filament glows in the dark. Null if unknown.")
    color_hex: Mapped[str | None] = mapped_column(String(8))
    multi_color_hexes: Mapped[str | None] = mapped_column(String(128))
    multi_color_direction: Mapped[str | None] = mapped_column(String(16))
    color_hue: Mapped[float | None] = mapped_column(
        comment="Precomputed hue (degrees, 0-360) of the colour, for sortable colour ordering (#113). "
        "Server-managed, not exposed on the API; NULL when no colour is set.",
    )
    external_id: Mapped[str | None] = mapped_column(String(256))
    low_stock_threshold: Mapped[float | None] = mapped_column(
        comment="Alert when total remaining weight across this filament's spools drops below this, in grams.",
    )
    reserve_count: Mapped[int | None] = mapped_column(
        comment="Number of unopened spare spools of this filament kept in reserve, tracked without a Spool row each.",
    )
    label_printed_at: Mapped[datetime | None] = mapped_column(
        comment="When a label was last printed for this filament (#93). Null means never printed.",
    )
    extra: Mapped[list["FilamentField"]] = relationship(
        back_populates="filament",
        cascade="save-update, merge, delete, delete-orphan",
        lazy="joined",
    )
    calibration_sessions: Mapped[list["CalibrationSession"]] = relationship(
        back_populates="filament",
        cascade="save-update, merge, delete, delete-orphan",
    )


class Spool(Base):
    __tablename__ = "spool"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    registered: Mapped[datetime] = mapped_column()
    first_used: Mapped[datetime | None] = mapped_column()
    last_used: Mapped[datetime | None] = mapped_column()
    price: Mapped[float | None] = mapped_column()
    filament_id: Mapped[int] = mapped_column(ForeignKey("filament.id"))
    filament: Mapped["Filament"] = relationship(back_populates="spools")
    initial_weight: Mapped[float | None] = mapped_column()
    spool_weight: Mapped[float | None] = mapped_column()
    used_weight: Mapped[float] = mapped_column()
    diameter: Mapped[float | None] = mapped_column(
        comment="Per-spool filament diameter override (#101). Null means use the filament's diameter.",
    )
    # Per-spool color override (#74). Null means use the filament's color. Mirrors the filament columns.
    color_hex: Mapped[str | None] = mapped_column(String(8))
    multi_color_hexes: Mapped[str | None] = mapped_column(String(128))
    multi_color_direction: Mapped[str | None] = mapped_column(String(16))
    location: Mapped[str | None] = mapped_column(String(64))
    printer_id: Mapped[int | None] = mapped_column(
        ForeignKey("printer.id"),
        comment="Optional printer this spool is assigned to (#75). Null means unassigned. Not a "
        "DB-level constraint; integrity is enforced in the application layer.",
    )
    printer: Mapped[Optional["Printer"]] = relationship(back_populates="spools")
    lot_nr: Mapped[str | None] = mapped_column(String(64))
    comment: Mapped[str | None] = mapped_column(String(1024))
    archived: Mapped[bool | None] = mapped_column()
    label_printed_at: Mapped[datetime | None] = mapped_column(
        comment="When a label was last printed for this spool (#93). Null means never printed.",
    )
    extra: Mapped[list["SpoolField"]] = relationship(
        back_populates="spool",
        cascade="save-update, merge, delete, delete-orphan",
        lazy="joined",
    )


class SpoolUsageEvent(Base):
    """A timestamped record of a single change to a spool's used_weight (#50).

    Intentionally has no ORM relationship back to Spool: get_by_id loads spools with
    joinedload("*") on the hot use/measure path, and a to-many relationship here would eager-load
    every event. Rows are queried directly by spool_id, cascade-deleted explicitly in spool.delete
    (SQLite doesn't enforce FKs) plus a DB-level ON DELETE CASCADE for the other backends.
    """

    __tablename__ = "spool_usage_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    spool_id: Mapped[int] = mapped_column(ForeignKey("spool.id", ondelete="CASCADE"), index=True)
    time: Mapped[datetime] = mapped_column(index=True)
    # One of: use, measure, update, reset, transfer.
    event_type: Mapped[str] = mapped_column(String(24))
    delta: Mapped[float] = mapped_column(
        comment="Applied change to used_weight in grams (sign: consumed positive, refilled negative).",
    )
    measured_weight: Mapped[float | None] = mapped_column(comment="Raw gross weight for measure events, in grams.")
    comment: Mapped[str | None] = mapped_column(String(1024))
    idempotency_key: Mapped[str | None] = mapped_column(String(64))


class CalibrationSession(Base):
    __tablename__ = "calibration_session"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    registered: Mapped[datetime] = mapped_column()
    filament_id: Mapped[int] = mapped_column(ForeignKey("filament.id", ondelete="CASCADE"))
    filament: Mapped["Filament"] = relationship(back_populates="calibration_sessions")
    status: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime | None] = mapped_column()
    completed_at: Mapped[datetime | None] = mapped_column()
    printer_name: Mapped[str | None] = mapped_column(String(256))
    nozzle_diameter: Mapped[float | None] = mapped_column()
    notes: Mapped[str | None] = mapped_column(String(1024))
    steps: Mapped[list["CalibrationStepResult"]] = relationship(
        back_populates="session",
        cascade="save-update, merge, delete, delete-orphan",
        lazy="joined",
    )


class CalibrationStepResult(Base):
    __tablename__ = "calibration_step_result"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("calibration_session.id", ondelete="CASCADE"))
    session: Mapped["CalibrationSession"] = relationship(back_populates="steps")
    step_type: Mapped[str] = mapped_column(String(64))
    inputs: Mapped[str | None] = mapped_column(Text())
    outputs: Mapped[str | None] = mapped_column(Text())
    selected_values: Mapped[str | None] = mapped_column(Text())
    notes: Mapped[str | None] = mapped_column(String(1024))
    confidence: Mapped[str | None] = mapped_column(String(32))
    recorded_at: Mapped[datetime] = mapped_column()


class Setting(Base):
    __tablename__ = "setting"

    key: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    value: Mapped[str] = mapped_column(Text())
    last_updated: Mapped[datetime] = mapped_column()


class User(Base):
    """An optional login account (#52).

    Named user_account because "user" is a reserved word in PostgreSQL/MySQL. Passwords are stored as
    a self-describing scrypt hash (see spoolman.users), never in plaintext.
    """

    __tablename__ = "user_account"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    # One of: admin (full access) or readonly (GET only). See spoolman.users.ROLES.
    role: Mapped[str] = mapped_column(String(16))
    registered: Mapped[datetime] = mapped_column()
    last_login: Mapped[datetime | None] = mapped_column()


class VendorField(Base):
    __tablename__ = "vendor_field"

    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendor.id", ondelete="CASCADE"), primary_key=True, index=True)
    vendor: Mapped["Vendor"] = relationship(back_populates="extra")
    key: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    value: Mapped[str] = mapped_column(Text())


class FilamentField(Base):
    __tablename__ = "filament_field"

    filament_id: Mapped[int] = mapped_column(
        ForeignKey("filament.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    filament: Mapped["Filament"] = relationship(back_populates="extra")
    key: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    value: Mapped[str] = mapped_column(Text())


class SpoolField(Base):
    __tablename__ = "spool_field"

    spool_id: Mapped[int] = mapped_column(ForeignKey("spool.id", ondelete="CASCADE"), primary_key=True, index=True)
    spool: Mapped["Spool"] = relationship(back_populates="extra")
    key: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    value: Mapped[str] = mapped_column(Text())


class Location(Base):
    """A named storage location, promoted to a first-class entity (issue #103).

    Locations become entities so custom fields can be attached to them — e.g. a synced
    temperature/humidity reading on a dry box. This is a parallel name registry: ``Spool.location``
    remains a plain string column and the existing ``/location`` string endpoints are unchanged, so
    integrations are unaffected. The registry is keyed by name.
    """

    __tablename__ = "location"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    registered: Mapped[datetime] = mapped_column()
    name: Mapped[str] = mapped_column(String(64))
    comment: Mapped[str | None] = mapped_column(String(1024))
    extra: Mapped[list["LocationField"]] = relationship(
        back_populates="location",
        cascade="save-update, merge, delete, delete-orphan",
        lazy="joined",
    )


class LocationField(Base):
    __tablename__ = "location_field"

    location_id: Mapped[int] = mapped_column(
        ForeignKey("location.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    location: Mapped["Location"] = relationship(back_populates="extra")
    key: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    value: Mapped[str] = mapped_column(Text())


class Printer(Base):
    """A first-class printer entity for per-printer spool assignment (issue #75 / #26).

    A minimal name registry so a spool can be assigned to a printer (via the nullable
    ``Spool.printer_id``) for multi-printer inventory tracking and usage attribution. Custom fields
    can be attached (e.g. an IP address or model) via the ``printer_field`` side-table. Assignment is
    optional and additive: an unassigned spool behaves exactly as before.
    """

    __tablename__ = "printer"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    registered: Mapped[datetime] = mapped_column()
    name: Mapped[str] = mapped_column(String(64))
    comment: Mapped[str | None] = mapped_column(String(1024))
    spools: Mapped[list["Spool"]] = relationship(back_populates="printer")
    extra: Mapped[list["PrinterField"]] = relationship(
        back_populates="printer",
        cascade="save-update, merge, delete, delete-orphan",
        lazy="joined",
    )


class PrinterField(Base):
    __tablename__ = "printer_field"

    printer_id: Mapped[int] = mapped_column(ForeignKey("printer.id", ondelete="CASCADE"), primary_key=True, index=True)
    printer: Mapped["Printer"] = relationship(back_populates="extra")
    key: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    value: Mapped[str] = mapped_column(Text())
