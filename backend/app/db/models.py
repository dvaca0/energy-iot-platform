from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class Delegation(Base):
    __tablename__ = "delegations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, unique=True, index=True)
    municipality: Mapped[str | None] = mapped_column(String, nullable=True)

    campuses = relationship("Campus", back_populates="delegation")


class Campus(Base):
    __tablename__ = "campuses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, index=True)
    location: Mapped[str | None] = mapped_column(String, nullable=True)

    delegation_id: Mapped[int] = mapped_column(ForeignKey("delegations.id"))
    delegation = relationship("Delegation", back_populates="campuses")

    organizational_units = relationship("OrganizationalUnit", back_populates="campus")
    buildings = relationship("Building", back_populates="campus")


class OrganizationalUnit(Base):
    __tablename__ = "organizational_units"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, index=True)
    unit_type: Mapped[str] = mapped_column(String, default="faculty")

    campus_id: Mapped[int] = mapped_column(ForeignKey("campuses.id"))
    campus = relationship("Campus", back_populates="organizational_units")

    buildings = relationship("Building", back_populates="organizational_unit")


class Building(Base):
    __tablename__ = "buildings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    code: Mapped[str] = mapped_column(String, unique=True, index=True)
    name: Mapped[str] = mapped_column(String, index=True)

    campus_id: Mapped[int] = mapped_column(ForeignKey("campuses.id"))
    organizational_unit_id: Mapped[int] = mapped_column(ForeignKey("organizational_units.id"))

    is_user_defined: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)

    # A development placeholder, not authoritative production metadata (ADR-0006).
    # Orthogonal to EnergyReading.context: readings taken here may still be
    # genuine production measurements, so this flag excludes the *building* from
    # building-level analytics without discarding the measurements themselves.
    is_placeholder: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    campus = relationship("Campus", back_populates="buildings")
    organizational_unit = relationship("OrganizationalUnit", back_populates="buildings")

    panels = relationship("ElectricalPanel", back_populates="building")
    deployments = relationship("Deployment", back_populates="building")


class ElectricalPanel(Base):
    __tablename__ = "electrical_panels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, index=True)

    building_id: Mapped[int] = mapped_column(ForeignKey("buildings.id"))
    notes: Mapped[str | None] = mapped_column(String, nullable=True)

    building = relationship("Building", back_populates="panels")
    deployments = relationship("Deployment", back_populates="electrical_panel")


class Node(Base):
    __tablename__ = "nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    code: Mapped[str] = mapped_column(String, unique=True, index=True)
    name: Mapped[str] = mapped_column(String)
    ip_address: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="offline")
    last_sync: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    buffer_pending: Mapped[int] = mapped_column(Integer, default=0)
    samples: Mapped[int] = mapped_column(Integer, default=0)

    # Identity and authorization. Legal values and their semantics live in
    # node_commission_states and are read through app.db.commissioning —
    # never restated here (ADR-0001, ADR-0002).
    hardware_kind: Mapped[str | None] = mapped_column(String, nullable=True)
    commission_state: Mapped[str] = mapped_column(String, nullable=False, default="registered")
    measurement_context: Mapped[str] = mapped_column(String, nullable=False, default="production")
    auth_token_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    commissioned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # ------------------------------------------------------------ ratings
    # Physical limits of the measurement hardware that travels with this node
    # (M8). All nullable: nothing is known until an operator enters it, and an
    # absent rating is safer than a guessed one — alert thresholds fall through
    # to the next source when these are NULL.
    #
    # A deployment's own values override these for the duration of a campaign,
    # because the panel changes but the clamp does not.
    ct_max_current_a: Mapped[float | None] = mapped_column(Float, nullable=True)
    nominal_voltage_v: Mapped[float | None] = mapped_column(Float, nullable=True)
    phase_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    warning_current_a: Mapped[float | None] = mapped_column(Float, nullable=True)
    critical_current_a: Mapped[float | None] = mapped_column(Float, nullable=True)
    emergency_current_a: Mapped[float | None] = mapped_column(Float, nullable=True)
    sustained_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    deployments = relationship("Deployment", back_populates="node")


class Deployment(Base):
    __tablename__ = "deployments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    node_id: Mapped[int] = mapped_column(ForeignKey("nodes.id"))
    building_id: Mapped[int] = mapped_column(ForeignKey("buildings.id"))
    electrical_panel_id: Mapped[int] = mapped_column(ForeignKey("electrical_panels.id"))

    start_date: Mapped[str] = mapped_column(String)
    # NULL means open-ended: the campaign has no scheduled end (ADR-0006).
    end_date: Mapped[str | None] = mapped_column(String, nullable=True)
    # Foreign key to deployment_statuses. The legal values and their semantics
    # live there and are read through app.db.lifecycle — never restated here.
    status: Mapped[str] = mapped_column(String, default="active")
    notes: Mapped[str | None] = mapped_column(String, nullable=True)

    # Operational truth: when measurement actually began and ended. Written by
    # the lifecycle transitions, never by an operator, and never editable once
    # set (M12 trigger). This pair — not start_date/end_date — is the window the
    # attribution resolver matches against, because a node handover happens at
    # an instant and a schedule is only accurate to the day.
    activated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # ------------------------------------------------------------ ratings
    # Physical limits of the installation this campaign measures (M8). These
    # take precedence over the node's own values, because the same node
    # measures a 100 A panel one month and a 400 A panel the next.
    #
    # All nullable. Enter what is known; leave the rest NULL and the threshold
    # resolver falls through to the node, then to a learned baseline, then to a
    # conservative safety ceiling.
    panel_main_breaker_a: Mapped[float | None] = mapped_column(Float, nullable=True)
    ct_max_current_a: Mapped[float | None] = mapped_column(Float, nullable=True)
    nominal_voltage_v: Mapped[float | None] = mapped_column(Float, nullable=True)
    phase_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    warning_current_a: Mapped[float | None] = mapped_column(Float, nullable=True)
    critical_current_a: Mapped[float | None] = mapped_column(Float, nullable=True)
    emergency_current_a: Mapped[float | None] = mapped_column(Float, nullable=True)
    sustained_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    node = relationship("Node", back_populates="deployments")
    building = relationship("Building", back_populates="deployments")
    electrical_panel = relationship("ElectricalPanel", back_populates="deployments")
    readings = relationship("EnergyReading", back_populates="deployment")


class EnergyReading(Base):
    __tablename__ = "energy_readings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Who measured it. Never null — a reading always has a node (ADR-0004).
    node_id: Mapped[int] = mapped_column(ForeignKey("nodes.id"))

    # Where it counts. Nullable since M4: a reading that no deployment covers is
    # stored unattributed rather than rejected. Written once at ingest from the
    # measurement's own timestamp, and never recomputed on read.
    building_id: Mapped[int | None] = mapped_column(ForeignKey("buildings.id"), nullable=True)
    deployment_id: Mapped[int | None] = mapped_column(ForeignKey("deployments.id"), nullable=True)
    electrical_panel_id: Mapped[int | None] = mapped_column(
        ForeignKey("electrical_panels.id"), nullable=True
    )

    # What kind of measurement this is. Declared, never inferred from the
    # presence of a deployment (ADR-0003). Legal values live in
    # measurement_contexts; nothing restates them.
    context: Mapped[str] = mapped_column(String, nullable=False, default="production")

    # When it was measured. Indexed, and the axis attribution is resolved on.
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True, default=datetime.utcnow)

    # When the server received it. Distinct from `timestamp`, because a replayed
    # edge buffer can deliver a week-old measurement seconds ago.
    ingested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    voltage: Mapped[float | None] = mapped_column(Float, nullable=True)
    current: Mapped[float | None] = mapped_column(Float, nullable=True)

    #: Instantaneous active power at the sample instant. Every meter measures
    #: this; it is the one quantity no collector may omit.
    power_kw: Mapped[float | None] = mapped_column(Float, nullable=True)

    #: LEGACY. Carried two meanings over the platform's life — a cumulative
    #: register until 2026-07-03 and per-interval energy from 2026-07-25
    #: (ADR-0007). Never written again. Read ONLY by
    #: app/services/energy_aggregate.py, which resolves the era from
    #: measurement_eras. Retained because it is historical evidence.
    energy_kwh: Mapped[float | None] = mapped_column(Float, nullable=True)

    # ---- canonical measurement contract (ADR-0007) ----
    #: Energy attributable to the interval this sample represents. THE
    #: analytics quantity: additive, immune to counter resets and gaps.
    interval_energy_kwh: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: Length of that interval. Without it the energy above is uninterpretable
    #: and gaps cannot be detected.
    interval_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: The device's own cumulative register, for reconciliation against a
    #: utility bill. No analytic ever differences this.
    meter_energy_kwh: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: How interval_energy_kwh was obtained: measured | counter_delta |
    #: power_integral. Provenance is part of the measurement — without it the
    #: number is unfalsifiable, which is what caused the 2026-07 incident.
    energy_source: Mapped[str | None] = mapped_column(String, nullable=True)
    power_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    frequency_hz: Mapped[float | None] = mapped_column(Float, nullable=True)

    phase_a_voltage: Mapped[float | None] = mapped_column(Float, nullable=True)
    phase_b_voltage: Mapped[float | None] = mapped_column(Float, nullable=True)
    phase_c_voltage: Mapped[float | None] = mapped_column(Float, nullable=True)

    phase_a_current: Mapped[float | None] = mapped_column(Float, nullable=True)
    phase_b_current: Mapped[float | None] = mapped_column(Float, nullable=True)
    phase_c_current: Mapped[float | None] = mapped_column(Float, nullable=True)

    deployment = relationship("Deployment", back_populates="readings")

    # Who measured it, reachable without going through the deployment. Callers
    # used to reach the node as reading.deployment.node, which breaks the moment
    # a reading is legitimately unattributed — node_id is NOT NULL precisely so
    # that "who measured this" always has an answer (ADR-0004).
    node = relationship("Node")
    building = relationship("Building")


class SmartPlug(Base):
    """Shelly Plug US Gen4 discovered by a Raspberry Pi.

    A smart plug is NOT an Energy Node: it is an accessory attached to a
    deployment, used to find out which outlet or appliance consumes the most
    during a measurement campaign.

    The permanent identity of a plug is its MAC address. The IP is volatile
    (DHCP) and is refreshed on every rediscovery, never used as identity.
    """

    __tablename__ = "smart_plugs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    mac: Mapped[str] = mapped_column(String, unique=True, index=True)
    model: Mapped[str] = mapped_column(String, default="Shelly Plug US Gen4")

    # Volatile network data, replaced on each discovery.
    ip_address: Mapped[str | None] = mapped_column(String, nullable=True)
    hostname: Mapped[str | None] = mapped_column(String, nullable=True)
    serial: Mapped[str | None] = mapped_column(String, nullable=True)
    firmware: Mapped[str | None] = mapped_column(String, nullable=True)
    rssi: Mapped[float | None] = mapped_column(Float, nullable=True)
    temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Which Raspberry Pi owns it, and where it is administratively.
    #
    # node_id is the *authoritative owner*, not merely the last reporter: the
    # first node to report a plug claims it, and reports from any other node
    # are rejected rather than silently overwriting ownership. Two Pis on the
    # same subnet discover the same plugs, so last-writer-wins would flip the
    # owner every cycle and split the plug's history across two nodes.
    # Ownership lives here, so it survives reboots, DHCP changes and
    # rediscovery, and is only reassigned through the explicit transfer
    # endpoint.
    node_id: Mapped[int | None] = mapped_column(ForeignKey("nodes.id"), nullable=True)
    owner_claimed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    building_id: Mapped[int | None] = mapped_column(ForeignKey("buildings.id"), nullable=True)
    deployment_id: Mapped[int | None] = mapped_column(ForeignKey("deployments.id"), nullable=True)

    # The assignment dialog sends free text; the label is kept verbatim so the
    # UI round-trips exactly, while *_id above is resolved when it matches.
    building_label: Mapped[str | None] = mapped_column(String, nullable=True)
    deployment_label: Mapped[str | None] = mapped_column(String, nullable=True)

    friendly_name: Mapped[str | None] = mapped_column(String, nullable=True)
    outlet_location: Mapped[str | None] = mapped_column(String, nullable=True)

    # Reported by the edge; a plug that disappears is kept, only flagged down.
    online: Mapped[bool] = mapped_column(Boolean, default=False)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Latest telemetry snapshot, so the live view needs no history join.
    power_w: Mapped[float | None] = mapped_column(Float, nullable=True)
    voltage_v: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_a: Mapped[float | None] = mapped_column(Float, nullable=True)
    power_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    energy_total_kwh: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    node = relationship("Node")
    building = relationship("Building")
    deployment = relationship("Deployment")
    readings = relationship("SmartPlugReading", back_populates="smart_plug")


class SmartPlugReading(Base):
    """Historical measurements for smart plugs.

    Deliberately separate from energy_readings: Energy Node history must not be
    mixed with accessory history, and the Energy Node tables are never touched.
    """

    __tablename__ = "smart_plug_readings"
    __table_args__ = (
        # Makes edge retries idempotent: a replayed buffer cannot duplicate.
        UniqueConstraint("smart_plug_id", "timestamp", name="uq_smart_plug_reading"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    smart_plug_id: Mapped[int] = mapped_column(ForeignKey("smart_plugs.id"), index=True)

    # Denormalized context, so history stays meaningful after reassignment.
    node_id: Mapped[int | None] = mapped_column(ForeignKey("nodes.id"), nullable=True)
    building_id: Mapped[int | None] = mapped_column(ForeignKey("buildings.id"), nullable=True)
    deployment_id: Mapped[int | None] = mapped_column(ForeignKey("deployments.id"), nullable=True)

    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True, default=datetime.utcnow)

    power_w: Mapped[float | None] = mapped_column(Float, nullable=True)
    voltage_v: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_a: Mapped[float | None] = mapped_column(Float, nullable=True)
    power_factor: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Cumulative counter reported by the device, plus the per-sample delta.
    energy_total_kwh: Mapped[float | None] = mapped_column(Float, nullable=True)
    energy_kwh: Mapped[float | None] = mapped_column(Float, nullable=True)

    temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    rssi: Mapped[float | None] = mapped_column(Float, nullable=True)

    smart_plug = relationship("SmartPlug", back_populates="readings")


class TariffPeriod(Base):
    __tablename__ = "tariff_periods"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tariff_name: Mapped[str] = mapped_column(String, default="GDMTH")
    period_name: Mapped[str] = mapped_column(String)
    start_hour: Mapped[int] = mapped_column(Integer)
    end_hour: Mapped[int] = mapped_column(Integer)
    price_per_kwh_mxn: Mapped[float] = mapped_column(Float)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
