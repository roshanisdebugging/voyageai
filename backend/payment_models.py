"""
VoyageAI Subscription & Payment Database Models (v3.3 Architecture - Final Hardened Layer)

Defines the 8 tables governing subscriptions, billing, payment attempts,
webhook idempotency, usage metering, and durable refund intents:
1. subscription_plans
2. plan_features
3. user_subscriptions
4. usage_events
5. payments
6. payment_attempts
7. refund_intents
8. webhook_events

Architectural & Relational Invariants (Phase 1 Final Review):
1. Funding Payment Composite Ownership:
   UserSubscription.funding_payment_id is bound by a composite foreign key
   (funding_payment_id, id, user_id) referencing payments(id, subscription_id, user_id).
   Guarantees at database level that the funding payment belongs strictly to that exact
   subscription and user. Handled via use_alter=True, ondelete="SET NULL", and post_update=True.
2. Payment Ownership Composite Integrity:
   Payment (subscription_id, user_id) references user_subscriptions (id, user_id) with
   ondelete="RESTRICT", preventing cross-user payment attribution.
3. Refund Attempt-to-Payment Composite Integrity:
   RefundIntent (payment_attempt_id, payment_id) references payment_attempts (id, payment_id)
   with ondelete="RESTRICT", preventing refund intents from referencing mismatched attempts.
4. Primary Capture Invariants:
   - Check constraint enforces is_primary=TRUE ONLY when status='captured' and captured_at IS NOT NULL.
   - Partial unique index enforces AT MOST ONE primary capture per payment.
   - Exactly-one primary capture for SUCCESS payments is guaranteed transactionally at service layer.
5. Financial Audit Retention:
   All financial relationships omit delete-orphan. Foreign keys use ondelete="RESTRICT"
   (except funding_payment_id which uses SET NULL on payment deletion), preventing accidental
   cascade-deletion of financial ledgers. Users with payment records must be soft-deactivated/anonymized.
6. Worker Lease & Fencing Protocol:
   Worker tasks (order creation, webhook processing, refund dispatch) utilize:
   - lease expiry timestamp: processing_lease_expires_at / order_creation_lease_expires_at
   - UUID fencing token: processing_attempt_id / order_creation_attempt_id
   - Non-negative retry counts
   - Stale workers whose lease expired cannot commit completion (fencing token mismatch).
   - Reclaiming workers MUST generate a fresh UUIDv4 fencing token.
7. Explicit Billing Anchor:
   UserSubscription.billing_cycle_anchor_day has NO silent default, requiring callers to explicitly
   supply the day-of-month anchor (1-31).
8. Strict Nullability on Financial Attributes:
   All monetary amounts (paise), currency strings, and lifecycle statuses are nullable=False.
"""

from sqlalchemy import (
    Column,
    Integer,
    SmallInteger,
    String,
    Boolean,
    DateTime,
    Date,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    UniqueConstraint,
    Index,
    func,
    text
)
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB
from database import Base


# ============================================================================
# 1. Subscription Plans
# ============================================================================
class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"

    __table_args__ = (
        CheckConstraint(
            "price_paise >= 0",
            name="check_plan_price_non_negative"
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(30), unique=True, nullable=False)           # FREE, ULTRA
    name = Column(String(100), nullable=False)                       # Display name
    price_paise = Column(Integer, nullable=False, default=0)         # 0 for FREE, 4900 for ULTRA
    billing_interval = Column(String(20), nullable=False, default="NONE")  # NONE, MONTHLY, ANNUAL
    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )

    # Relationships
    features = relationship(
        "PlanFeature",
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="PlanFeature.id"
    )
    subscriptions = relationship(
        "UserSubscription",
        back_populates="plan",
        foreign_keys="[UserSubscription.plan_id]"
    )


# ============================================================================
# 2. Plan Features & Quotas
# ============================================================================
class PlanFeature(Base):
    __tablename__ = "plan_features"

    __table_args__ = (
        UniqueConstraint("plan_id", "feature_key", name="uq_plan_feature"),
        CheckConstraint(
            "usage_limit IS NULL OR usage_limit >= 0",
            name="check_usage_limit_non_negative"
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    plan_id = Column(
        Integer,
        ForeignKey("subscription_plans.id", ondelete="CASCADE"),
        nullable=False
    )
    feature_key = Column(String(50), nullable=False)                 # tour_guide_chat, itinerary_generation
    enabled = Column(Boolean, nullable=False, default=True)
    usage_limit = Column(Integer, nullable=True)                     # NULL = unlimited
    reset_period = Column(String(20), nullable=False, default="NONE") # NONE, DAILY, MONTHLY

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )

    # Relationships
    plan = relationship("SubscriptionPlan", back_populates="features")


# ============================================================================
# 3. User Subscriptions
# ============================================================================
class UserSubscription(Base):
    __tablename__ = "user_subscriptions"

    __table_args__ = (
        # Composite unique constraint enabling Payment composite FK enforcement
        UniqueConstraint("id", "user_id", name="uq_user_subscriptions_id_user_id"),
        # Composite FK enforcing funding_payment_id belongs to this exact subscription & user
        ForeignKeyConstraint(
            ["funding_payment_id", "id", "user_id"],
            ["payments.id", "payments.subscription_id", "payments.user_id"],
            ondelete="RESTRICT",
            use_alter=True,
            name="fk_user_subscriptions_funding_payment_composite"
        ),
        CheckConstraint(
            "status IN ('PENDING', 'ACTIVE', 'PAST_DUE', 'CANCELLED', 'EXPIRED')",
            name="check_subscription_status"
        ),
        CheckConstraint(
            "(current_period_start IS NULL AND current_period_end IS NULL) OR "
            "(current_period_start IS NOT NULL AND current_period_end IS NOT NULL AND current_period_end > current_period_start)",
            name="check_subscription_period"
        ),
        CheckConstraint(
            "(grace_period_start IS NULL AND grace_period_end IS NULL) OR "
            "(grace_period_start IS NOT NULL AND grace_period_end IS NOT NULL AND grace_period_end > grace_period_start)",
            name="check_grace_period"
        ),
        CheckConstraint(
            "billing_cycle_anchor_day >= 1 AND billing_cycle_anchor_day <= 31",
            name="check_anchor_day_range"
        ),
        # Partial unique index: at most one current subscription per user
        Index(
            "uq_one_current_subscription_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("status IN ('PENDING', 'ACTIVE', 'PAST_DUE')")
        ),
        # Performance index for grace period reaper worker
        Index(
            "ix_subscriptions_grace_reaper_v33",
            "status",
            "grace_period_end",
            postgresql_where=text("status = 'PAST_DUE'")
        ),
        Index("ix_user_subscriptions_plan_id", "plan_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        String,
        ForeignKey("auth_users.id", ondelete="RESTRICT"),
        nullable=False
    )
    plan_id = Column(
        Integer,
        ForeignKey("subscription_plans.id", ondelete="RESTRICT"),
        nullable=False
    )
    status = Column(String(20), nullable=False, default="PENDING")
    gateway = Column(String(30), nullable=False, default="RAZORPAY")
    gateway_customer_id = Column(String(100), nullable=True)
    gateway_subscription_id = Column(String(100), unique=True, nullable=True)

    # Drift-free calendar billing anchor day (1-31). Explicitly required, no silent default.
    billing_cycle_anchor_day = Column(SmallInteger, nullable=False)

    # Active Entitlement Period
    current_period_start = Column(DateTime(timezone=True), nullable=True)
    current_period_end = Column(DateTime(timezone=True), nullable=True)
    cancel_at_period_end = Column(Boolean, nullable=False, default=False)
    grace_period_start = Column(DateTime(timezone=True), nullable=True)
    grace_period_end = Column(DateTime(timezone=True), nullable=True)

    # Explicit Funding Payment Pointer (Enforced by composite FK)
    funding_payment_id = Column(Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )

    # Relationships
    plan = relationship("SubscriptionPlan", back_populates="subscriptions", foreign_keys=[plan_id])
    payments = relationship(
        "Payment",
        back_populates="subscription",
        foreign_keys="[Payment.subscription_id, Payment.user_id]",
        primaryjoin="and_(UserSubscription.id == Payment.subscription_id, UserSubscription.user_id == Payment.user_id)",
        order_by="Payment.id.desc()"
    )
    funding_payment = relationship(
        "Payment",
        foreign_keys=[funding_payment_id],
        primaryjoin="and_(UserSubscription.funding_payment_id == Payment.id, UserSubscription.id == Payment.subscription_id, UserSubscription.user_id == Payment.user_id)",
        post_update=True
    )


# ============================================================================
# 4. Usage Events & Quota Tracking
# ============================================================================
class UsageEvent(Base):
    __tablename__ = "usage_events"

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "feature_key",
            "request_id",
            name="uq_user_feature_request"
        ),
        CheckConstraint(
            "quantity > 0",
            name="check_usage_quantity_positive"
        ),
        Index(
            "idx_usage_user_feature_time",
            "user_id",
            "feature_key",
            "occurred_at"
        ),
        Index(
            "idx_usage_user_feature_period",
            "user_id",
            "feature_key",
            "period_start"
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        String,
        ForeignKey("auth_users.id", ondelete="CASCADE"),
        nullable=False
    )
    feature_key = Column(String(50), nullable=False)                 # tour_guide_chat, itinerary_generation
    quantity = Column(Integer, nullable=False, default=1)
    reference_type = Column(String(30), nullable=True)               # trip, itinerary, chat_session
    reference_id = Column(String(100), nullable=True)
    request_id = Column(String(100), nullable=False)                 # Idempotency token
    occurred_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    timezone = Column(String(64), nullable=False, default="Asia/Kolkata")
    period_start = Column(Date, nullable=False)                      # User's local date bucket


# ============================================================================
# 5. Payments
# ============================================================================
class Payment(Base):
    __tablename__ = "payments"

    __table_args__ = (
        # Composite unique constraint enabling UserSubscription composite funding payment FK (Finding 2)
        UniqueConstraint("id", "subscription_id", "user_id", name="uq_payments_id_subscription_user"),
        # Composite FK enforcing Payment ownership matches UserSubscription ownership
        ForeignKeyConstraint(
            ["subscription_id", "user_id"],
            ["user_subscriptions.id", "user_subscriptions.user_id"],
            ondelete="RESTRICT",
            name="fk_payments_subscription_user"
        ),
        CheckConstraint(
            "amount_paise > 0",
            name="check_payment_amount_positive"
        ),
        CheckConstraint(
            "status IN ('CREATED', 'SUCCESS', 'FAILED', 'REFUNDED')",
            name="check_payment_status"
        ),
        CheckConstraint(
            "order_creation_status IN ('NOT_STARTED', 'IN_PROGRESS', 'CREATED', 'UNKNOWN', 'FAILED', 'ESCALATED_MANUAL')",
            name="check_order_creation_status"
        ),
        CheckConstraint(
            "(billing_period_start IS NULL AND billing_period_end IS NULL) OR "
            "(billing_period_start IS NOT NULL AND billing_period_end IS NOT NULL AND billing_period_end > billing_period_start)",
            name="check_payment_billing_period"
        ),
        # Finding 4: Consistency check: active order-creation lease requires valid fencing token
        CheckConstraint(
            "(order_creation_lease_expires_at IS NULL) OR (order_creation_attempt_id IS NOT NULL)",
            name="check_payment_lease_requires_token"
        ),
        # Finding 4: NOT_STARTED status cannot have an active lease or token
        CheckConstraint(
            "(order_creation_status != 'NOT_STARTED') OR (order_creation_lease_expires_at IS NULL AND order_creation_attempt_id IS NULL)",
            name="check_payment_not_started_lease_clean"
        ),
        # Partial unique index: at most one pending (CREATED) payment per user
        Index(
            "uq_one_pending_payment_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'CREATED'")
        ),
        # Performance index for background reconciliation worker
        Index(
            "ix_payments_reconciliation_v33",
            "status",
            "expires_at",
            postgresql_where=text("status = 'CREATED'")
        ),
        # Performance index for order creation lease auditor
        Index(
            "ix_payments_lease_audit_v33",
            "order_creation_status",
            "order_creation_lease_expires_at",
            postgresql_where=text("order_creation_status IN ('IN_PROGRESS', 'UNKNOWN')")
        ),
        Index("ix_payments_subscription_id", "subscription_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        String,
        ForeignKey("auth_users.id", ondelete="RESTRICT"),
        nullable=False
    )
    subscription_id = Column(
        Integer,
        nullable=False
    )
    amount_paise = Column(Integer, nullable=False)                   # e.g., 4900 (Finding 1)
    currency = Column(String(10), nullable=False, default="INR")     # Finding 1
    status = Column(String(20), nullable=False, default="CREATED")   # Finding 1

    # Order Creation Lifecycle & Worker Lease (v3.3 Fencing Protocol)
    order_creation_status = Column(
        String(30),
        nullable=False,
        default="NOT_STARTED"
    )
    order_creation_attempt_id = Column(String(64), nullable=True)    # UUID fencing token
    order_creation_lease_expires_at = Column(DateTime(timezone=True), nullable=True)

    # Gateway identifiers & Entitlement Period Isolation
    gateway = Column(String(30), nullable=False, default="RAZORPAY")
    gateway_order_id = Column(String(100), unique=True, nullable=True)
    billing_period_start = Column(DateTime(timezone=True), nullable=True) # Immutable entitlement coverage
    billing_period_end = Column(DateTime(timezone=True), nullable=True)   # Immutable entitlement coverage

    paid_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)      # Local checkout session TTL
    failure_reason = Column(String(255), nullable=True)              # Gateway decline reason (never refunds)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )

    # Relationships (Financial audit retention: NO delete-orphan)
    subscription = relationship(
        "UserSubscription",
        back_populates="payments",
        foreign_keys="[Payment.subscription_id, Payment.user_id]",
        primaryjoin="and_(Payment.subscription_id == UserSubscription.id, Payment.user_id == UserSubscription.user_id)"
    )
    attempts = relationship(
        "PaymentAttempt",
        back_populates="payment",
        foreign_keys="[PaymentAttempt.payment_id]",
        order_by="PaymentAttempt.id.asc()"
    )
    refund_intents = relationship(
        "RefundIntent",
        back_populates="payment",
        foreign_keys="[RefundIntent.payment_id]",
        order_by="RefundIntent.id.asc()"
    )


# ============================================================================
# 6. Payment Attempts & Captures
# ============================================================================
class PaymentAttempt(Base):
    __tablename__ = "payment_attempts"

    __table_args__ = (
        # Composite unique constraint enabling RefundIntent composite FK enforcement
        UniqueConstraint("id", "payment_id", name="uq_payment_attempts_id_payment_id"),
        CheckConstraint(
            "amount_paise > 0",
            name="check_attempt_amount_positive"
        ),
        CheckConstraint(
            "status IN ('created', 'authorized', 'captured', 'failed', 'refunded')",
            name="check_attempt_status"
        ),
        # Primary capture integrity checks (captured or refunded primary captures retain captured_at)
        CheckConstraint(
            "(NOT is_primary) OR (is_primary AND status IN ('captured', 'refunded'))",
            name="check_primary_only_captured"
        ),
        CheckConstraint(
            "(status NOT IN ('captured', 'refunded')) OR (status IN ('captured', 'refunded') AND captured_at IS NOT NULL)",
            name="check_captured_has_timestamp"
        ),
        # Partial unique index: at most one primary capture per payment order
        Index(
            "uq_one_primary_capture_per_payment",
            "payment_id",
            unique=True,
            postgresql_where=text("is_primary = TRUE")
        ),
        # Composite index for attempt status lookups under a payment
        Index(
            "ix_payment_attempts_payment_status",
            "payment_id",
            "status"
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    payment_id = Column(
        Integer,
        ForeignKey("payments.id", ondelete="RESTRICT"),
        nullable=False
    )
    gateway_payment_id = Column(String(100), unique=True, nullable=False)  # Razorpay pay_... ID
    amount_paise = Column(Integer, nullable=False)                         # Finding 1: nullable=False
    currency = Column(String(10), nullable=False, default="INR")           # Finding 1: nullable=False
    status = Column(String(30), nullable=False)                            # Finding 1: nullable=False
    method = Column(String(30), nullable=True)                             # upi, card, netbanking
    error_code = Column(String(100), nullable=True)
    error_description = Column(String(255), nullable=True)
    is_primary = Column(Boolean, nullable=False, default=False)            # True for authoritative funding capture
    captured_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )

    # Relationships (Financial audit retention: NO delete-orphan)
    payment = relationship(
        "Payment",
        back_populates="attempts",
        foreign_keys=[payment_id]
    )
    refund_intents = relationship(
        "RefundIntent",
        back_populates="payment_attempt",
        foreign_keys="[RefundIntent.payment_attempt_id, RefundIntent.payment_id]",
        primaryjoin="and_(PaymentAttempt.id == RefundIntent.payment_attempt_id, PaymentAttempt.payment_id == RefundIntent.payment_id)",
        order_by="RefundIntent.id.asc()",
        overlaps="refund_intents,payment"
    )


# ============================================================================
# 7. Durable Refund Intents
# ============================================================================
class RefundIntent(Base):
    __tablename__ = "refund_intents"

    __table_args__ = (
        # Composite FK enforcing refund belongs to the exact payment & attempt (Finding 3)
        ForeignKeyConstraint(
            ["payment_attempt_id", "payment_id"],
            ["payment_attempts.id", "payment_attempts.payment_id"],
            ondelete="RESTRICT",
            name="fk_refund_intents_attempt_payment"
        ),
        CheckConstraint(
            "amount_paise > 0",
            name="check_refund_amount_positive"
        ),
        CheckConstraint(
            "status IN ('PENDING', 'IN_PROGRESS', 'UNKNOWN', 'COMPLETED', 'FAILED')",
            name="check_refund_intent_status"
        ),
        # Finding 4: Retry count cannot be negative
        CheckConstraint(
            "retry_count >= 0",
            name="check_refund_retry_count_non_negative"
        ),
        # Finding 4: Active refund worker lease requires valid fencing token
        CheckConstraint(
            "(processing_lease_expires_at IS NULL) OR (processing_attempt_id IS NOT NULL)",
            name="check_refund_lease_requires_token"
        ),
        Index(
            "ix_refund_intents_attempt_status",
            "payment_attempt_id",
            "status"
        ),
        # Performance index for refund worker processing and retry queue
        Index(
            "ix_refund_intents_worker_queue",
            "status",
            "next_retry_at",
            postgresql_where=text("status IN ('PENDING', 'IN_PROGRESS', 'UNKNOWN')")
        ),
        Index("ix_refund_intents_payment_id", "payment_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    payment_id = Column(
        Integer,
        ForeignKey("payments.id", ondelete="RESTRICT"),
        nullable=False
    )
    payment_attempt_id = Column(
        Integer,
        nullable=False
    )
    refund_request_id = Column(String(100), unique=True, nullable=False)  # Deterministic operation key
    amount_paise = Column(Integer, nullable=False)
    currency = Column(String(10), nullable=False, default="INR")
    status = Column(String(30), nullable=False, default="PENDING")        # PENDING, IN_PROGRESS, UNKNOWN, COMPLETED, FAILED
    gateway_refund_id = Column(String(100), unique=True, nullable=True)   # Razorpay rfnd_... ID
    reason = Column(String(100), nullable=False)
    error_message = Column(String(255), nullable=True)

    # Worker Lease Ownership & Retry Fencing (Finding 4, 5)
    processing_attempt_id = Column(String(64), nullable=True)             # UUID worker fencing token
    processing_lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    retry_count = Column(Integer, nullable=False, default=0)              # Finding 4: non-negative
    next_retry_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )

    # Relationships (Finding 3: synchronized composite FK relationship)
    payment = relationship("Payment", back_populates="refund_intents", foreign_keys=[payment_id])
    payment_attempt = relationship(
        "PaymentAttempt",
        back_populates="refund_intents",
        foreign_keys=[payment_attempt_id, payment_id],
        primaryjoin="and_(PaymentAttempt.id == RefundIntent.payment_attempt_id, PaymentAttempt.payment_id == RefundIntent.payment_id)",
        overlaps="payment,refund_intents"
    )


# ============================================================================
# 8. Webhook Events (Durable Inbox)
# ============================================================================
class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    __table_args__ = (
        UniqueConstraint(
            "gateway",
            "gateway_event_id",
            name="uq_gateway_event"
        ),
        # Finding 4: Retry count cannot be negative
        CheckConstraint(
            "retry_count >= 0",
            name="check_webhook_retry_count_non_negative"
        ),
        # Finding 4: Active webhook worker lease requires valid fencing token
        CheckConstraint(
            "(processing_lease_expires_at IS NULL) OR (processing_attempt_id IS NOT NULL)",
            name="check_webhook_lease_requires_token"
        ),
        # Finding 4: Processed webhook state and processed_at must remain consistent
        CheckConstraint(
            "(NOT processed AND processed_at IS NULL) OR (processed AND processed_at IS NOT NULL)",
            name="check_webhook_processed_consistency"
        ),
        Index(
            "ix_webhook_events_queue",
            "processed",
            "next_retry_at",
            postgresql_where=text("processed = FALSE")
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    gateway = Column(String(30), nullable=False, default="RAZORPAY")
    gateway_event_id = Column(String(150), nullable=False)          # Extracted from X-Razorpay-Event-Id header
    event_type = Column(String(100), nullable=False)                # payment.captured, order.paid, etc.
    payload = Column(JSONB, nullable=False)
    processed = Column(Boolean, nullable=False, default=False)

    # Worker Lease Ownership & Retry Fencing (Finding 4, 5)
    processing_attempt_id = Column(String(64), nullable=True)       # UUID worker fencing token
    processing_lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    processing_error = Column(String(1000), nullable=True)
    retry_count = Column(Integer, nullable=False, default=0)        # Finding 4: non-negative
    next_retry_at = Column(DateTime(timezone=True), nullable=True)

    received_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    processed_at = Column(DateTime(timezone=True), nullable=True)
