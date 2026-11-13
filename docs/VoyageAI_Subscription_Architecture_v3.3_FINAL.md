# VoyageAI Subscription & Payment Architecture — v3.3 (FINAL)

---

## 1. Architecture Overview and Design Principles

This specification defines the authoritative architecture for subscription billing, payment reconciliation, webhook processing, usage metering, and access entitlement for **VoyageAI**. The backend is built with **FastAPI**, **PostgreSQL (Neon)**, **SQLAlchemy 2.0**, and integrates with **Razorpay**.

### 1.1 Core System Principles

1. **At-Least-Once Gateway Semantics**: Razorpay delivery guarantees are at-least-once. All webhooks, payment captures, order lookups, and refund operations must assume duplicate delivery, out-of-order execution, and transient network dropouts.
2. **Fail-Closed Entitlement**: Access to paid capabilities (**ULTRA**) is never granted on ambiguous, missing, or unverified records. A missing timestamp, unknown transaction status, or unverified capture always defaults to the **FREE** tier.
3. **Strict Separation of Gateway Calls and Database Transactions**: External HTTP calls to Razorpay must **never** be executed within an open database transaction holding table or row locks. All interactions follow a two-phase transactional pattern:
   - **Phase 1 (Pre-Call Intent)**: Persist durable intent in PostgreSQL and commit.
   - **External Step**: Dispatch gateway HTTP call outside any database transaction.
   - **Phase 2 (Post-Call Settlement)**: Open a new transaction, lock the relevant records, reconcile gateway responses, and commit.
4. **Deterministic Global Lock Ordering**: To prevent distributed and database-level deadlocks, all multi-row operations acquire row locks strictly according to the global hierarchy:
   $$\text{auth\_users} \longrightarrow \text{user\_subscriptions} \longrightarrow \text{payments} \longrightarrow \text{payment\_attempts} \longrightarrow \text{refund\_intents} \longrightarrow \text{webhook\_events}$$
5. **Billing Anchor Preservation (No Drift)**: Calendar-based billing anchors must be preserved across months of varying lengths (e.g., January 31 $\rightarrow$ February 28/29 $\rightarrow$ March 31). Month-to-month clamping must not permanently drift future renewal dates.
6. **Entitlement-Period Payment Isolation**: Every successful payment funds an immutable, explicit billing period $[t_{\text{start}}, t_{\text{end}})$. A refund against a payment only invalidates the exact entitlement period funded by that payment and never revokes access funded by a subsequent renewal.
7. **No Unchecked Assumptions**: Local clock expiration (`expires_at <= now()`) does not prove gateway finality. Late-arriving gateway captures on locally dead records must be quarantined for automated refund or administrative credit and must never silently activate an expired or cancelled subscription.

---

## 2. Business Rules and Subscription Entitlements

### 2.1 Plan Tiers and Quotas

| Plan Code | Price (Paise) | Billing Interval | Tour-Guide Chat Quota | Itinerary Generation Quota | Explore, Highlights & Feed |
|---|---|---|---|---|---|
| **FREE** | ₹0 (0 paise) | None (Default) | 10 user messages / day | 2 successful generations / month | **Disabled** (HTTP 403) |
| **ULTRA** | ₹49 (4900 paise) | Monthly (Calendar Anchor) | 50 user messages / day | 10 successful generations / month | **Enabled** (Full Access) |

### 2.2 Usage Accounting Rules
1. **Chat Messages**:
   - Each accepted user message counts toward the daily quota.
   - Assistant responses, system messages, and client-side validation failures do not consume quota.
   - Daily quotas reset at **00:00:00 local time** based on the user's timezone stored in `user_profiles.timezone`.
   - If `user_profiles.timezone` is missing, NULL, or invalid, the system strictly falls back to `Asia/Kolkata`.
2. **Itineraries**:
   - Only **successful** itinerary generation events consume itinerary quota.
   - Failed generations (e.g., AI model timeouts, 5xx errors, internal pipeline aborts) must not consume quota.
   - Monthly itinerary quota resets on the user's local calendar month boundary (or subscription renewal anchor for Ultra subscribers).

### 2.3 Subscription Lifecycle Business Rules
1. **New User Baseline**: New registered users receive FREE tier access immediately without requiring an initial row in `user_subscriptions`.
2. **Ultra Activation**: Ultra access is granted strictly after verified, authoritative settlement of a 4900 paise payment.
3. **Renewal Failure & Grace Period**:
   - If an Ultra renewal charge fails or is uncompleted at period end, the subscription transitions to `PAST_DUE`.
   - The user retains full Ultra access for a **3-day grace period** ($\text{grace\_period\_end} = \text{current\_period\_end} + 3\text{ days}$).
   - Daily renewal reminders are triggered during the grace period.
   - If a renewal payment succeeds while `PAST_DUE`, the subscription returns to `ACTIVE`, and the new billing period is anchored to the original `current_period_end` (the user does not receive "free days" that drift their renewal date).
4. **Voluntary Cancellation**:
   - When a user cancels, `cancel_at_period_end` is set to `TRUE`.
   - The subscription status remains `ACTIVE`. Ultra access continues uninterrupted until `current_period_end`.
   - At `current_period_end`, the subscription transitions to `EXPIRED`, and the user falls back to the FREE tier.
5. **Renewal Record Mechanics**:
   - A successful renewal updates the existing `user_subscriptions` row.
   - Each renewal creates a new, distinct `payments` record and associated `payment_attempts` records.
6. **Post-Expiration Purchase**:
   - If an expired user purchases Ultra again, a new `user_subscriptions` row is created, establishing a new billing cycle anchor.

---

## 3. Complete Database Schema and Relationships

```
                     ┌──────────────────────┐
                     │      auth_users      │
                     └──────────┬───────────┘
                                │ 1
                                │
                                │ 0..*
                     ┌──────────▼───────────┐
                     │  user_subscriptions  │
                     └──────────┬───────────┘
                                │ 1
                                │
                                │ 0..*
                     ┌──────────▼───────────┐
                     │       payments       │
                     └──────────┬───────────┘
                                │ 1
                   ┌────────────┴────────────┐
                   │ 1..*                    │ 0..*
        ┌──────────▼───────────┐  ┌──────────▼───────────┐
        │   payment_attempts   │  │    refund_intents    │
        └──────────────────────┘  └──────────────────────┘

  ┌─────────────────────────────────────────────────────────┐
  │                     webhook_events                      │
  │     (Independent durable gateway event ingestion inbox) │
  └─────────────────────────────────────────────────────────┘
```

### 3.1 Conceptual Table Definitions

#### `user_subscriptions`
Tracks customer subscription status and billing periods.
- `id`: `Integer`, Primary Key, Autoincrement.
- `user_id`: `String`, Foreign Key $\rightarrow$ `auth_users.id`, NOT NULL, Indexed.
- `plan_id`: `Integer`, Foreign Key $\rightarrow$ `subscription_plans.id`, NOT NULL.
- `status`: `VARCHAR(20)`, NOT NULL, Default `'PENDING'`.
  - Check: `status IN ('PENDING', 'ACTIVE', 'PAST_DUE', 'CANCELLED', 'EXPIRED')`.
- `gateway`: `VARCHAR(30)`, Default `'RAZORPAY'`.
- `gateway_customer_id`: `VARCHAR(100)`, Nullable.
- `gateway_subscription_id`: `VARCHAR(100)`, Unique, Nullable.
- `billing_cycle_anchor_day`: `SmallInteger`, NOT NULL, Default `1`. (Preserves anchor day 1–31 across variable-length months).
- `current_period_start`: `TIMESTAMPTZ`, Nullable.
- `current_period_end`: `TIMESTAMPTZ`, Nullable.
- `cancel_at_period_end`: `Boolean`, NOT NULL, Default `FALSE`.
- `grace_period_start`: `TIMESTAMPTZ`, Nullable.
- `grace_period_end`: `TIMESTAMPTZ`, Nullable.
- `created_at`, `updated_at`: `TIMESTAMPTZ`, NOT NULL, Server Default `NOW()`.

#### `payments`
Tracks individual commercial payment orders and billing period associations.
- `id`: `Integer`, Primary Key, Autoincrement.
- `user_id`: `String`, Foreign Key $\rightarrow$ `auth_users.id`, NOT NULL, Indexed.
- `subscription_id`: `Integer`, Foreign Key $\rightarrow$ `user_subscriptions.id`, NOT NULL, Indexed.
- `amount_paise`: `Integer`, NOT NULL, Check (`amount_paise > 0`).
- `currency`: `VARCHAR(10)`, NOT NULL, Default `'INR'`.
- `status`: `VARCHAR(20)`, NOT NULL, Default `'CREATED'`.
  - Check: `status IN ('CREATED', 'SUCCESS', 'FAILED', 'REFUNDED')`.
- `order_creation_status`: `VARCHAR(30)`, NOT NULL, Default `'NOT_STARTED'`.
  - Check: `order_creation_status IN ('NOT_STARTED', 'IN_PROGRESS', 'CREATED', 'UNKNOWN', 'FAILED', 'ESCALATED_MANUAL')`.
- `order_creation_attempt_id`: `VARCHAR(64)`, Nullable (UUID fencing token).
- `order_creation_lease_expires_at`: `TIMESTAMPTZ`, Nullable.
- `gateway`: `VARCHAR(30)`, NOT NULL, Default `'RAZORPAY'`.
- `gateway_order_id`: `VARCHAR(100)`, Unique, Nullable.
- `billing_period_start`: `TIMESTAMPTZ`, Nullable (Immutable entitlement coverage start).
- `billing_period_end`: `TIMESTAMPTZ`, Nullable (Immutable entitlement coverage end).
- `paid_at`: `TIMESTAMPTZ`, Nullable.
- `expires_at`: `TIMESTAMPTZ`, Nullable (Local checkout session TTL).
- `failure_reason`: `VARCHAR(255)`, Nullable (Restricted strictly to gateway decline codes; never refund data).
- `created_at`, `updated_at`: `TIMESTAMPTZ`, NOT NULL, Server Default `NOW()`.

#### `payment_attempts`
Tracks every discrete gateway payment transaction attempt under a Razorpay order.
- `id`: `Integer`, Primary Key, Autoincrement.
- `payment_id`: `Integer`, Foreign Key $\rightarrow$ `payments.id`, NOT NULL, Indexed.
- `gateway_payment_id`: `VARCHAR(100)`, Unique, NOT NULL (Razorpay `pay_...` ID).
- `amount_paise`: `Integer`, NOT NULL, Check (`amount_paise > 0`).
- `currency`: `VARCHAR(10)`, NOT NULL, Default `'INR'`.
- `status`: `VARCHAR(30)`, NOT NULL.
  - Check: `status IN ('created', 'authorized', 'captured', 'failed', 'refunded')`.
- `method`: `VARCHAR(30)`, Nullable (e.g., `'upi'`, `'card'`, `'netbanking'`).
- `error_code`: `VARCHAR(100)`, Nullable.
- `error_description`: `VARCHAR(255)`, Nullable.
- `is_primary`: `Boolean`, NOT NULL, Default `FALSE`.
- `captured_at`: `TIMESTAMPTZ`, Nullable.
- `created_at`, `updated_at`: `TIMESTAMPTZ`, NOT NULL, Server Default `NOW()`.

#### `refund_intents`
Durable, idempotent tracking of refund operations.
- `id`: `Integer`, Primary Key, Autoincrement.
- `payment_id`: `Integer`, Foreign Key $\rightarrow$ `payments.id`, NOT NULL, Indexed.
- `payment_attempt_id`: `Integer`, Foreign Key $\rightarrow$ `payment_attempts.id`, NOT NULL, Indexed.
- `refund_request_id`: `VARCHAR(100)`, Unique, NOT NULL (Deterministic client/internal operation key).
- `amount_paise`: `Integer`, NOT NULL, Check (`amount_paise > 0`).
- `currency`: `VARCHAR(10)`, NOT NULL, Default `'INR'`.
- `status`: `VARCHAR(30)`, NOT NULL, Default `'PENDING'`.
  - Check: `status IN ('PENDING', 'IN_PROGRESS', 'UNKNOWN', 'COMPLETED', 'FAILED')`.
- `gateway_refund_id`: `VARCHAR(100)`, Unique, Nullable (Razorpay `rfnd_...` ID).
- `reason`: `VARCHAR(100)`, NOT NULL.
- `error_message`: `VARCHAR(255)`, Nullable.
- `created_at`, `updated_at`: `TIMESTAMPTZ`, NOT NULL, Server Default `NOW()`.

#### `webhook_events`
Durable inbox for gateway event ingestion.
- `id`: `Integer`, Primary Key, Autoincrement.
- `gateway`: `VARCHAR(30)`, NOT NULL, Default `'RAZORPAY'`.
- `gateway_event_id`: `VARCHAR(150)`, NOT NULL.
- `event_type`: `VARCHAR(100)`, NOT NULL.
- `payload`: `JSONB`, NOT NULL.
- `processed`: `Boolean`, NOT NULL, Default `FALSE`.
- `processing_lease_expires_at`: `TIMESTAMPTZ`, Nullable.
- `processing_error`: `VARCHAR(1000)`, Nullable.
- `retry_count`: `Integer`, NOT NULL, Default `0`.
- `next_retry_at`: `TIMESTAMPTZ`, Nullable.
- `received_at`: `TIMESTAMPTZ`, NOT NULL, Server Default `NOW()`.
- `processed_at`: `TIMESTAMPTZ`, Nullable.

---

## 4. State Machines

### 4.1 Order Creation State Machine
Governs the creation of the external Razorpay order.

```
       [ Checkout Intent: TX1 Commit ]
                      │
                      ▼
               ┌─────────────┐
               │ NOT_STARTED │
               └──────┬──────┘
                      │ Claim Lease (TX2)
                      ▼
               ┌─────────────┐
        ┌──────┤ IN_PROGRESS ├──────┐
        │      └──────┬──────┘      │
        │             │             │
(External API   (Client 4xx   (Timeout / Crash /
 Success: TX3)   Error: TX3)   Lease Expired: TX3)
        ▼             ▼             ▼
  ┌───────────┐ ┌───────────┐ ┌───────────┐
  │  CREATED  │ │  FAILED   │ │  UNKNOWN  │
  └───────────┘ └───────────┘ └─────┬─────┘
                                    │
                                    ├─────────────────────────┐
                                    │ Reconciled / Webhook    │ Manual Escalation
                                    │ Resolves Order ID       │ after Max Retries
                                    ▼                         ▼
                              ┌───────────┐             ┌───────────────────┐
                              │  CREATED  │             │ ESCALATED_MANUAL  │
                              └───────────┘             └───────────────────┘
```

### 4.2 Payment Settlement State Machine
Governs commercial status of the local payment record.

```
                       ┌─────────┐
                       │ CREATED │
                       └────┬────┘
                            │
       ┌────────────────────┼────────────────────┐
       │ Primary Capture    │ In-Flight Bank     │ Terminal Gateway Expiry
       │ Validated (TX)     │ Authorization      │ Verified + now() >= expires_at
       ▼                    ▼                    ▼
 ┌───────────┐        ┌───────────┐        ┌───────────┐
 │  SUCCESS  │        │  CREATED  │        │  FAILED   │
 └─────┬─────┘        │(expires+5)│        └───────────┘
       │              └───────────┘
       ├─────────────────────────┐
       │ Full Refund Completed   │ Partial Refund Completed
       ▼                         ▼
 ┌───────────┐             ┌───────────┐
 │ REFUNDED  │             │  SUCCESS  │ (Preserved; refund_intents
 └───────────┘             └───────────┘  track balance)
```

### 4.3 Payment Attempt State Machine
Tracks individual Razorpay transactions (`pay_...`).

```
                    ┌─────────┐
                    │ created │
                    └────┬────┘
                         │
            ┌────────────┴────────────┐
            │ Bank Auth OK            │ Gateway Rejection
            ▼                         ▼
     ┌────────────┐            ┌────────────┐
     │ authorized │            │   failed   │
     └─────┬──────┘            └────────────┘
           │
           │ Capture Succeeded
           ▼
     ┌────────────┐
     │  captured  │
     └─────┬──────┘
           │
           │ Full Refund Executed
           ▼
     ┌────────────┐
     │  refunded  │
     └────────────┘
```

### 4.4 Subscription Lifecycle State Machine

```
                  [ Checkout Initiated ]
                            │
                            ▼
                    ┌───────────────┐
                    │    PENDING    │
                    └───────┬───────┘
                            │
          ┌─────────────────┴─────────────────┐
          │ Payment SUCCESS                   │ Payment Terminally FAILED
          ▼                                   ▼
  ┌───────────────┐                   ┌───────────────┐
  │    ACTIVE     │                   │   CANCELLED   │
  └───────┬───────┘                   └───────────────┘
          │
          ├─────────────────────────────────────────┐
          │ Billing Cycle Ends                      │ User Requests Voluntary
          │ AND Renewal Payment Fails               │ Cancellation
          ▼                                         ▼
  ┌───────────────┐                         ┌───────────────┐
  │   PAST_DUE    │                         │    ACTIVE     │
  │ (Exact 3-Day  │                         │ (cancel_at_   │
  │  Grace Period)│                         │  period_end)  │
  └───────┬───────┘                         └───────┬───────┘
          │                                         │
          ├───────────────────┐                     │
          │ Renewal Succeeded │ Grace Period Expired│ now() >= current_period_end
          │ (Anchored to prior│ (now() > grace_end) │
          │  period end)      │                     │
          ▼                   ▼                     ▼
  ┌───────────────┐   ┌───────────────────────────────────┐
  │    ACTIVE     │   │              EXPIRED              │
  └───────────────┘   │  (Revokes Ultra access; fallback  │
                      │   to FREE tier immediately)       │
                      └───────────────────────────────────┘
```

### 4.5 Webhook Ingestion State Machine
- `PENDING`: Durably committed in `webhook_events`, waiting for worker pickup.
- `IN_PROGRESS`: Claimed by a worker via `processing_lease_expires_at`.
- `PROCESSED`: Successfully executed; domain records updated atomically.
- `RETRY_PENDING`: Transient failure encountered; backoff timestamp set.
- `DEAD_LETTER`: Exceeded maximum retry count (5) or non-retryable structural failure.

### 4.6 Refund Intent State Machine
- `PENDING`: Registered locally; balance validated.
- `IN_PROGRESS`: External call in-flight.
- `UNKNOWN`: Network timeout; requires gateway reconciliation.
- `COMPLETED`: Gateway confirmed refund; balance updated.
- `FAILED`: Gateway rejected with 4xx; reservation released.

---

## 5. Checkout and Order Creation Workflow

### 5.1 Concurrency, Serialization, and Worker Leases
To eliminate double order creation when users click repeatedly or network calls timeout:

1. **User Lock**: Every checkout request locks the user row:
   ```sql
   SELECT id FROM auth_users WHERE id = :user_id FOR UPDATE;
   ```
2. **Reuse Existing Active Draft**:
   If an unexpired `payments` record exists with `status = 'CREATED'`:
   - If `order_creation_status == 'CREATED'`: Return existing `gateway_order_id` (safe resume).
   - If `order_creation_status == 'IN_PROGRESS'` and `order_creation_lease_expires_at > NOW()`: Return HTTP 409 / Retry-After: 3s.
   - If `order_creation_status in ('IN_PROGRESS', 'UNKNOWN')` and lease expired: Transition to `UNKNOWN` and trigger reconciliation.
3. **Lease Protocol (TX1 $\rightarrow$ External Call $\rightarrow$ TX2)**:
   - **TX1**: Persist draft `payments` row (`order_creation_status = 'IN_PROGRESS'`, `order_creation_attempt_id = :uuid`, `order_creation_lease_expires_at = NOW() + INTERVAL '30s'`). Commit TX1.
   - **External Step**: Call `razorpay_client.order.create({...})` with `receipt = f"rcpt_{payment.id}_{uuid[:8]}"` and `notes = {"payment_id": str(payment.id), "user_id": user_id}`.
   - **TX2**: Lock `payments` row `FOR UPDATE`. If `order_creation_attempt_id == :uuid`:
     - Succeeded: Update `gateway_order_id = order.id`, `order_creation_status = 'CREATED'`, `expires_at = NOW() + INTERVAL '15m'`. Commit TX2.
     - Failed (4xx): Update `order_creation_status = 'FAILED'`, `status = 'FAILED'`. Commit TX2.
     - Timeout / Exception: Update `order_creation_status = 'UNKNOWN'`. Commit TX2.

---

## 6. Payment Authorization and Capture Workflow

1. **Client Submission**: Client receives `gateway_order_id`, opens Razorpay Checkout modal, and completes payment.
2. **Dual Arrival Paths**: Settlement can be triggered by client callback (`POST /api/subscriptions/verify-payment`) or asynchronous webhook (`payment.captured` / `order.paid`).
3. **Primary Capture Qualification**:
   An attempt qualifies as the **primary funding capture** if and only if:
   - `status == 'captured'`
   - `amount_paise == payment.amount_paise` (4900 paise)
   - `currency == payment.currency` (`INR`)
   - No other attempt on this payment is marked `is_primary = TRUE`.
4. **Duplicate Capture Handling**:
   If a second capture arrives with the same `gateway_order_id`:
   - It is inserted into `payment_attempts` with `is_primary = FALSE`.
   - The primary capture remains untouched.
   - A `refund_intents` record is automatically generated to refund the duplicate transaction.

---

## 7. Webhook Ingestion and Processing Workflow

### 7.1 Two-Phase Transactional Webhook Architecture

```
                       [ Incoming Webhook Request ]
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ PHASE 1: Durable Ingestion & Fast ACK (TX1)                            │
│ 1. Read request.body() as raw bytes.                                   │
│ 2. Verify HMAC-SHA256 signature against X-Razorpay-Signature header.   │
│    If invalid: Return HTTP 400 (Abort).                                │
│ 3. Extract event ID from header: X-Razorpay-Event-Id.                  │
│    If header missing: Parse payload["event_id"].                       │
│ 4. Open TX1:                                                           │
│    INSERT INTO webhook_events (                                        │
│        gateway, gateway_event_id, event_type, payload, processed       │
│    ) VALUES (                                                          │
│        'RAZORPAY', :event_id, :event_type, :payload, FALSE             │
│    ) ON CONFLICT (gateway, gateway_event_id) DO NOTHING;               │
│    Commit TX1.                                                         │
│ 5. Return HTTP 200 OK immediately to Razorpay.                         │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ PHASE 2: Worker Processing (TX2)                                       │
│ 1. Open TX2.                                                           │
│ 2. Lock event:                                                         │
│    SELECT * FROM webhook_events WHERE id = :id FOR UPDATE;             │
│    If processed == TRUE: Commit TX2 & Return.                          │
│ 3. Parse entity from payload:                                          │
│    - If event_type == "payment.captured": Entity is Payment.           │
│    - If event_type == "order.paid": Entity is Order.                   │
│ 4. Acquire Domain Entity Locks in Strict Global Order:                 │
│    - Lock user_subscriptions FOR UPDATE                                │
│    - Lock payments FOR UPDATE                                          │
│    - Lock payment_attempts FOR UPDATE                                  │
│ 5. Execute state changes, capture recording, and entitlement.          │
│ 6. UPDATE webhook_events SET processed = TRUE, processed_at = NOW();   │
│    Commit TX2.                                                         │
└────────────────────────────────────────────────────────────────────────┘
```

### 7.2 Webhook Error Handling and Worker Recovery
- **Retryable Errors** (e.g., database lock timeouts, connection glitches):
  - Roll back TX2.
  - Set `retry_count += 1`, `next_retry_at = NOW() + (2 ^ retry_count) * INTERVAL '5s'`, `processing_lease_expires_at = NULL`.
- **Non-Retryable Errors** (e.g., malformed JSON, corrupted internal data):
  - Roll back domain changes in TX2.
  - In a new transaction: `UPDATE webhook_events SET processed = FALSE, processing_error = :err, next_retry_at = NULL`. Flag for admin review.
- **Worker Crash Recovery**:
  - Background sweeper inspects `webhook_events WHERE processed = FALSE AND processing_lease_expires_at <= NOW()`.
  - Clears expired leases and reschedules processing.

---

## 8. Reconciliation and Crash Recovery

### 8.1 Late Capture and Anomaly Quarantine Matrix

| Local `payments.status` | Local `user_subscriptions.status` | Gateway Discovery | System Action & Entitlement Impact |
|---|---|---|---|
| `CREATED` | `PENDING` | Valid Capture Verified | **Normal Activation**: Settle payment `SUCCESS`, transition subscription `ACTIVE`. |
| `FAILED` | `CANCELLED` | Valid Capture Discovered | **Late Capture Anomaly**: Record attempt `captured (is_primary=FALSE)`. Do NOT activate subscription. Dispatch automated full refund. Alert user. |
| `FAILED` | `EXPIRED` | Valid Capture Discovered | **Late Capture Anomaly**: Record attempt. Do NOT reactivate expired subscription. Dispatch automated full refund. |
| `SUCCESS` | `ACTIVE` | Duplicate Capture Discovered | **Duplicate Capture**: Record attempt `captured (is_primary=FALSE)`. Subscription unchanged. Dispatch automated refund for duplicate attempt. |
| `REFUNDED` | Any | New Capture Discovered | **Critical Anomaly**: Quarantine attempt. Do NOT grant access. Alert operations. |

### 8.2 Safe SQLAlchemy 2.0 Reconciliation Pseudocode

```python
from datetime import datetime, timezone, timedelta
from typing import Literal
import logging
from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

def reconcile_payment_workflow(payment_id: int, db_factory) -> str:
    """
    Authoritative reconciliation workflow.
    Executes external API calls with ZERO database transactions open.
    Adheres strictly to SQLAlchemy 2.0 explicit transaction boundaries.
    """
    # Step 1: Read payment references (Quick read transaction)
    with db_factory() as session:
        stmt = select(Payment).where(Payment.id == payment_id)
        payment = session.scalar(stmt)
        if not payment or not payment.gateway_order_id:
            return "NOOP"
        order_id = payment.gateway_order_id
        expected_amount = payment.amount_paise
        expected_currency = payment.currency

    # Step 2: External Gateway API Call (NO DB TRANSACTION OPEN)
    try:
        rp_order = razorpay_client.order.fetch(order_id)
        rp_payments_page = razorpay_client.order.payments(order_id)
        gateway_items = rp_payments_page.get("items", [])
    except Exception as exc:
        logger.warning(f"Gateway inquiry failed for order {order_id}: {exc}")
        return "RETRY_LATER"

    # Step 3: Reconcile and Settle in Database (Single atomic transaction with global lock ordering)
    now = datetime.now(timezone.utc)
    with db_factory() as session:
        with session.begin():
            # 1. Lock user_subscriptions first (Global Hierarchy)
            sub_id_stmt = select(Payment.subscription_id).where(Payment.id == payment_id)
            sub_id = session.scalar(sub_id_stmt)
            
            sub = session.scalar(
                select(UserSubscription)
                .where(UserSubscription.id == sub_id)
                .with_for_update()
            )

            # 2. Lock payments second
            locked_payment = session.scalar(
                select(Payment)
                .where(Payment.id == payment_id)
                .with_for_update()
            )

            # 3. Synchronize all attempts into payment_attempts
            _sync_gateway_attempts(session, locked_payment.id, gateway_items)

            # 4. Filter authoritative primary captures
            valid_captures = [
                item for item in gateway_items
                if item.get("status") == "captured"
                and item.get("amount") == expected_amount
                and item.get("currency") == expected_currency
            ]

            # Scenario A: Local Payment is already FAILED or REFUNDED (Late Capture)
            if locked_payment.status in ("FAILED", "REFUNDED"):
                if valid_captures:
                    logger.critical(f"LATE CAPTURE on {locked_payment.status} payment {payment_id}!")
                    # Quarantine capture and generate refund intent
                    for cap in valid_captures:
                        _create_refund_intent_record(
                            session, locked_payment.id, cap["id"], cap["amount"], "LATE_CAPTURE_QUARANTINE"
                        )
                    return "LATE_CAPTURE_REFUND_DISPATCHED"
                return "NOOP"

            # Scenario B: Local Payment is CREATED and Valid Capture Exists
            if locked_payment.status == "CREATED" and len(valid_captures) >= 1:
                primary = min(valid_captures, key=lambda x: x["created_at"])
                duplicates = [c for c in valid_captures if c["id"] != primary["id"]]

                # Settle Primary
                _mark_primary_attempt(session, locked_payment.id, primary["id"])
                locked_payment.status = "SUCCESS"
                locked_payment.paid_at = datetime.fromtimestamp(primary["created_at"], tz=timezone.utc)
                locked_payment.updated_at = now

                # Activate Subscription safely if eligible
                if sub and sub.status in ("PENDING", "PAST_DUE"):
                    _activate_subscription_period(session, sub, locked_payment, now)

                # Queue automated refunds for excess captures
                for dup in duplicates:
                    _create_refund_intent_record(
                        session, locked_payment.id, dup["id"], dup["amount"], "DUPLICATE_CAPTURE_AUTO_REFUND"
                    )

                return "SUCCESS"

            # Scenario C: In-Flight Bank Authorizations
            in_flight = [i for i in gateway_items if i.get("status") in ("authorized", "pending")]
            if in_flight or rp_order.get("status") == "attempted":
                if locked_payment.expires_at and locked_payment.expires_at <= now + timedelta(minutes=5):
                    locked_payment.expires_at = now + timedelta(minutes=10)
                return "IN_FLIGHT"

            # Scenario D: Order Expired with Zero Captures
            if locked_payment.expires_at and now >= locked_payment.expires_at:
                locked_payment.status = "FAILED"
                locked_payment.failure_reason = "EXPIRED_UNPAID"
                locked_payment.updated_at = now

                if sub and sub.status == "PENDING":
                    sub.status = "CANCELLED"
                    sub.updated_at = now

                return "FAILED"

    return "RETRY_LATER"
```

---

## 9. Subscription Activation and Renewal

### 9.1 Drift-Free Calendar Billing Anchor Arithmetic
To prevent renewal drift (e.g., January 31 $\rightarrow$ February 28 $\rightarrow$ March 28), the original day of month is stored in `billing_cycle_anchor_day`.

```python
import calendar
from datetime import datetime, timezone

def calculate_calendar_period_end(start_date: datetime, anchor_day: int) -> datetime:
    """
    Computes drift-free monthly billing period end dates.
    Clamps to month end when necessary, but preserves anchor for future months.
    """
    # Advance to next month
    next_year = start_date.year + (start_date.month // 12)
    next_month = (start_date.month % 12) + 1
    
    # Determine maximum days in the target month (handles leap years)
    max_days = calendar.monthrange(next_year, next_month)[1]
    clamped_day = min(anchor_day, max_days)
    
    return start_date.replace(
        year=next_year,
        month=next_month,
        day=clamped_day,
        hour=start_date.hour,
        minute=start_date.minute,
        second=start_date.second,
        microsecond=start_date.microsecond
    )
```

### 9.2 Context-Aware Entitlement Period Resolution
- **Initial Purchase**:
  - `start_date = now()`
  - `anchor_day = now().day`
  - `end_date = calculate_calendar_period_end(start_date, anchor_day)`
- **Normal Renewal (ACTIVE)**:
  - `start_date = sub.current_period_end`
  - `end_date = calculate_calendar_period_end(start_date, sub.billing_cycle_anchor_day)`
- **Grace Period Renewal (PAST_DUE)**:
  - **Preserves Billing Anchor**: `start_date = sub.current_period_end` (the period date that just expired).
  - `end_date = calculate_calendar_period_end(start_date, sub.billing_cycle_anchor_day)`
  - *Outcome*: The customer pays for the full month; renewal date does not creep forward.
- **Post-Expiration Reactivation (EXPIRED)**:
  - Creates a new subscription row.
  - `start_date = now()`
  - `anchor_day = now().day`
  - `end_date = calculate_calendar_period_end(start_date, anchor_day)`

---

## 10. Grace Period and Cancellation

### 10.1 Three-Day Grace Period Execution
- **Trigger**: Renewal date reached, no successful payment captured.
- **State Transition**:
  - `user_subscriptions.status = 'PAST_DUE'`
  - `grace_period_start = current_period_end`
  - `grace_period_end = current_period_end + INTERVAL '3 days'`
- **Entitlement**: Ultra access remains enabled while `NOW() < grace_period_end`.
- **Communication**: Automated reminders sent at $T+0$, $T+24\text{h}$, and $T+48\text{h}$.

### 10.2 Grace Expiry and Reaper Cooperation
- **Dual Expiry Paths**:
  1. **Background Reaper Job** (Runs hourly):
     ```sql
     UPDATE user_subscriptions
     SET status = 'EXPIRED',
         grace_period_start = NULL,
         grace_period_end = NULL,
         updated_at = NOW()
     WHERE status = 'PAST_DUE'
       AND grace_period_end <= NOW();
     ```
  2. **Inline Access Guard / Checkout Enforcement**:
     If a user arrives after `grace_period_end` before the reaper runs:
     - Access guard immediately treats entitlement as FREE.
     - Checkout endpoint updates status to `EXPIRED` inline, unblocking `uq_one_current_subscription_per_user`.

### 10.3 Voluntary Cancellation Mechanics
- User clicks "Cancel Subscription":
  - Sets `user_subscriptions.cancel_at_period_end = TRUE`.
  - Status remains `ACTIVE`.
  - Ultra access remains fully active until `current_period_end`.
  - When `NOW() >= current_period_end`, status transitions to `EXPIRED`.

---

## 11. Usage Metering and Quota Enforcement

### 11.1 Daily Chat Quota Enforcement
```python
def check_and_consume_chat_quota(user_id: str, db: Session) -> bool:
    """
    Validates and logs chat quota consumption.
    Counts accepted user messages in user's local timezone day.
    """
    now_utc = datetime.now(timezone.utc)
    user_tz = _get_user_timezone(user_id, db)
    local_now = now_utc.astimezone(user_tz)
    local_today = local_now.date()

    # Determine limit based on current verified entitlement
    entitlement = check_user_subscription_access(user_id, db)
    daily_limit = 50 if entitlement["tier"] == "ULTRA" else 10

    # Atomic count of today's accepted messages
    count = db.scalar(
        select(func.count(UsageEvent.id))
        .where(
            UsageEvent.user_id == user_id,
            UsageEvent.feature_key == "tour_guide_chat",
            UsageEvent.period_start == local_today
        )
    )

    if count >= daily_limit:
        return False

    # Record event
    event = UsageEvent(
        user_id=user_id,
        feature_key="tour_guide_chat",
        quantity=1,
        request_id=str(uuid.uuid4()),
        period_start=local_today,
        timezone=str(user_tz)
    )
    db.add(event)
    db.flush()
    return True
```

### 11.2 Monthly Itinerary Quota Enforcement
- Only successful itinerary completions generate a `UsageEvent(feature_key='itinerary_generation')`.
- Free users: Maximum 2 / month.
- Ultra users: Maximum 10 / month.
- Failed generations log an audit entry in application logs but never write to `usage_events`.

---

## 12. Entitlement and Access Guard (Fail-Closed)

### 12.1 Comprehensive Access Guard Logic

```python
def check_user_subscription_access(user_id: str, db: Session) -> dict:
    """
    Authoritative, fail-closed access guard.
    Verifies subscription state, dates, funding payment, and refund status.
    """
    now = datetime.now(timezone.utc)

    # 1. Fetch current subscription
    sub = db.scalar(
        select(UserSubscription)
        .where(
            UserSubscription.user_id == user_id,
            UserSubscription.status.in_(["ACTIVE", "PAST_DUE"])
        )
    )

    if not sub:
        return {"tier": "FREE", "has_ultra_access": False, "reason": "NO_ACTIVE_RECORD"}

    # 2. Guard against missing or corrupted period timestamps
    if not sub.current_period_start or not sub.current_period_end:
        logger.critical(f"INTEGRITY VIOLATION: Subscription {sub.id} has NULL period timestamps!")
        return {"tier": "FREE", "has_ultra_access": False, "reason": "CORRUPTED_METADATA"}

    # 3. Evaluate PAST_DUE Status
    if sub.status == "PAST_DUE":
        if sub.grace_period_end and now < sub.grace_period_end:
            return {
                "tier": "ULTRA",
                "has_ultra_access": True,
                "in_grace_period": True,
                "grace_ends_at": sub.grace_period_end
            }
        return {"tier": "FREE", "has_ultra_access": False, "reason": "GRACE_EXPIRED"}

    # 4. Evaluate ACTIVE Status
    if sub.status == "ACTIVE":
        # Check period expiration (even if reaper has not run)
        if now >= sub.current_period_end:
            return {"tier": "FREE", "has_ultra_access": False, "reason": "PERIOD_EXPIRED"}

        # 5. Verify Funding Payment Integrity
        # Find the successful payment that covers this exact entitlement period
        funding_payment = db.scalar(
            select(Payment)
            .where(
                Payment.subscription_id == sub.id,
                Payment.status == "SUCCESS",
                Payment.billing_period_start == sub.current_period_start,
                Payment.billing_period_end == sub.current_period_end
            )
        )

        if not funding_payment:
            logger.critical(f"INTEGRITY VIOLATION: No SUCCESS payment covers period for Subscription {sub.id}!")
            return {"tier": "FREE", "has_ultra_access": False, "reason": "UNFUNDED_PERIOD"}

        # Check verified primary capture
        primary_capture = db.scalar(
            select(PaymentAttempt)
            .where(
                PaymentAttempt.payment_id == funding_payment.id,
                PaymentAttempt.is_primary == True,
                PaymentAttempt.status == "captured"
            )
        )
        if not primary_capture:
            logger.critical(f"INTEGRITY VIOLATION: Funding Payment {funding_payment.id} lacks verified primary capture!")
            return {"tier": "FREE", "has_ultra_access": False, "reason": "UNVERIFIED_CAPTURE"}

        return {
            "tier": "ULTRA",
            "has_ultra_access": True,
            "cancel_at_period_end": sub.cancel_at_period_end,
            "period_end": sub.current_period_end
        }

    return {"tier": "FREE", "has_ultra_access": False}
```

---

## 13. Refund and Dispute Workflows

### 13.1 Durable Refund Intent Protocol
To prevent duplicate payouts during timeouts or backend crashes, all refunds follow a durable reservation protocol:

```
[ Refund Request: dispatch_refund_intent ]
                   │
                   ▼
┌────────────────────────────────────────────────────────┐
│ TX1: Reserve Refund Balance Locally                    │
│ 1. Lock payment_attempts row FOR UPDATE.               │
│ 2. Sum existing reservations:                          │
│    SELECT SUM(amount_paise) FROM refund_intents        │
│    WHERE payment_attempt_id = :id                      │
│      AND status IN ('PENDING', 'IN_PROGRESS',          │
│                     'UNKNOWN', 'COMPLETED');           │
│ 3. If reserved + request > attempt.amount_paise:       │
│    Raise ValueError (Exceeds capturable balance).      │
│ 4. Insert RefundIntent(status='IN_PROGRESS',           │
│    refund_request_id=:key). Commit TX1.                │
└──────────────────┬─────────────────────────────────────┘
                   │
                   ▼
┌────────────────────────────────────────────────────────┐
│ External Gateway Call (NO TRANSACTION HELD)            │
│ Call razorpay_client.payment.refund(attempt_id, {      │
│     "amount": amount,                                  │
│     "notes": {"refund_request_id": key}                │
│ })                                                     │
└──────────────────┬─────────────────────────────────────┘
                   │
         ┌─────────┴─────────┐
         │ Succeeded         │ Network Timeout / 5xx
         ▼                   ▼
┌─────────────────┐ ┌─────────────────┐
│ TX2a: Complete  │ │ TX2b: UNKNOWN   │
│ Set COMPLETED   │ │ Set UNKNOWN.    │
│ gateway_rfnd_id │ │ Reconcile via   │
│ Commit TX2a.    │ │ gateway refunds.│
└─────────────────┘ └─────────────────┘
```

### 13.2 Billing Period Isolation on Refunds
- When a refund reaches `COMPLETED`, the system inspects `payments.billing_period_start` and `payments.billing_period_end` of the refunded payment.
- If the user's active subscription has already advanced to a subsequent billing period (`sub.current_period_start > payment.billing_period_end`), **access is not revoked**. The refund is financial only.
- If the user's active subscription is currently in the period funded by this payment (`sub.current_period_start == payment.billing_period_start`):
  - In a full refund: Subscription transitions to `CANCELLED`, access revoked immediately.
  - In a partial refund: Access is preserved; partial refund audit log is updated.

---

## 14. Transaction Boundaries and Lock Ordering

### 14.1 Global Lock Hierarchy
Any workflow locking multiple tables must strictly acquire locks in this order:
$$\mathbf{auth\_users} \longrightarrow \mathbf{user\_subscriptions} \longrightarrow \mathbf{payments} \longrightarrow \mathbf{payment\_attempts} \longrightarrow \mathbf{refund\_intents} \longrightarrow \mathbf{webhook\_events}$$

### 14.2 Workflow Transaction Boundary Matrix

| Workflow | Phase 1 (Pre-Call) | Gateway Action | Phase 2 (Post-Call) |
|---|---|---|---|
| **Checkout Order Creation** | Lock `auth_users`. Persist draft `payments (order_creation_status='IN_PROGRESS')`. Commit. | Call `razorpay.order.create()`. | Lock `payments`. Update `gateway_order_id`, `status='CREATED'`. Commit. |
| **Payment Reconciliation** | Quick read of order/payment IDs. Commit. | Call `razorpay.order.fetch()` & `order.payments()`. | Lock `user_subscriptions` $\rightarrow$ `payments` $\rightarrow$ `payment_attempts`. Settle state. Commit. |
| **Webhook Ingestion** | Insert raw payload into `webhook_events`. Commit. | None. | Immediate HTTP 200 to gateway. |
| **Webhook Processing** | Lock `webhook_events`. Commit. | None (Uses payload or calls gateway if stale). | Lock `user_subscriptions` $\rightarrow$ `payments`. Update state, mark `processed=TRUE`. Commit. |
| **Refund Dispatch** | Lock `payments` $\rightarrow$ `payment_attempts`. Insert `refund_intents (IN_PROGRESS)`. Commit. | Call `razorpay.payment.refund()`. | Lock `refund_intents`. Set `COMPLETED` or `UNKNOWN`. Commit. |

---

## 15. Idempotency and Duplicate Prevention

1. **Client Checkout Idempotency**:
   - `auth_users` row lock serializes checkout button clicks.
   - Reuses existing unexpired `CREATED` payment record; prevents multiple order generation.
2. **Gateway Order Idempotency**:
   - Deterministic receipt: `f"rcpt_{payment.id}_{attempt_uuid[:8]}"`.
   - Notes metadata contains `"payment_id"`.
3. **Webhook Ingestion Idempotency**:
   - Unique constraint `uq_gateway_event` on `(gateway, gateway_event_id)`.
   - `INSERT ... ON CONFLICT DO NOTHING` drops duplicates at the database level.
4. **Primary Capture Idempotency**:
   - Unique partial index `uq_one_primary_capture_per_payment` on `payment_attempts (payment_id) WHERE is_primary = TRUE`.
   - Guarantees at most one primary capture per payment order.
5. **Refund Request Idempotency**:
   - Unique constraint on `refund_intents.refund_request_id`.
   - Dispatches refund with identical `notes.refund_request_id`.

---

## 16. Background Workers and Retry Policies

| Worker Name | Frequency | Target Query / Predicate | Action Taken |
|---|---|---|---|
| **Webhook Processor** | Continuous / Every 5s | `webhook_events WHERE processed = FALSE AND (next_retry_at IS NULL OR next_retry_at <= NOW())` | Claims lease, locks domain rows, settles payments/subscriptions. |
| **Payment Reconciler** | Every 5 minutes | `payments WHERE status = 'CREATED' AND expires_at <= NOW()` | Queries Razorpay API, identifies terminal status, frees indexes. |
| **Grace Period Reaper** | Hourly | `user_subscriptions WHERE status = 'PAST_DUE' AND grace_period_end <= NOW()` | Transitions status to `EXPIRED`. Revokes access. |
| **Refund Reconciler** | Every 10 minutes | `refund_intents WHERE status = 'UNKNOWN'` | Inquires gateway payment refund list; finalizes `COMPLETED` or `FAILED`. |
| **Stale Lease Sweeper** | Every 15 minutes | `payments WHERE order_creation_status = 'IN_PROGRESS' AND order_creation_lease_expires_at <= NOW()` | Transitions to `UNKNOWN`, queues for reconciliation. |

---

## 17. Failure Scenarios and Recovery Matrix

| Failure Mode | Point of Failure | Detection Mechanism | Automated Recovery Action |
|---|---|---|---|
| **Worker Crash During Order Creation** | External order created on Razorpay, server process killed before saving `gateway_order_id`. | Stale Lease Sweeper detects `order_creation_lease_expires_at <= NOW()`. | Sweeper marks `UNKNOWN`. Webhook uses `notes.payment_id` to link `gateway_order_id` and complete activation. |
| **Double Webhook Delivery** | Razorpay delivers identical `order.paid` concurrently to two instances. | Database constraint `uq_gateway_event` on `webhook_events`. | One instance inserts; second hits `ON CONFLICT DO NOTHING` and returns HTTP 200. |
| **Bank Capture After Checkout Expiry** | User pays at $T+14\text{m}$, gateway captures at $T+16\text{m}$ (after local 15m expiry). | Webhook arrives or reconciler sees capture on `FAILED` payment. | **Quarantined**: Attempt recorded as non-primary. Auto-refund intent dispatched. Subscription not reactivated. |
| **Duplicate Card Debits** | User card charged twice by payment network for one order. | Reconciler / Webhook detects 2 captured attempts for one `payment_id`. | Earliest capture activates Ultra. Second capture triggers automatic refund intent. |
| **Gateway Timeout on Refund Call** | Refund HTTP request dispatched, socket hangs, status unknown. | Exception handler sets `refund_intents.status = 'UNKNOWN'`. | Refund Reconciler polls gateway refund list using `notes.refund_request_id` and settles state. |

---

## 18. Database Constraints and Indexes

### 18.1 Constraints & Lifecycle Releases

| Table | Constraint / Index Name | Definition | Lifecycle Release Trigger |
|---|---|---|---|
| `user_subscriptions` | `uq_one_current_subscription_per_user` | `UNIQUE (user_id) WHERE status IN ('PENDING', 'ACTIVE', 'PAST_DUE')` | Released when subscription transitions to **`CANCELLED`** or **`EXPIRED`**. |
| `payments` | `uq_one_pending_payment_per_user` | `UNIQUE (user_id) WHERE status = 'CREATED'` | Released when payment transitions to **`SUCCESS`** or **`FAILED`**. |
| `payment_attempts` | `uq_one_primary_capture_per_payment` | `UNIQUE (payment_id) WHERE is_primary = TRUE` | Immutable once set; guarantees at most one funding capture per order. |
| `payment_attempts` | `uq_gateway_payment_id` | `UNIQUE (gateway_payment_id)` | Permanent gateway transaction deduplication. |
| `refund_intents` | `uq_refund_request_id` | `UNIQUE (refund_request_id)` | Permanent refund operation deduplication. |
| `webhook_events` | `uq_gateway_event` | `UNIQUE (gateway, gateway_event_id)` | Permanent gateway event deduplication. |

### 18.2 Performance Indexes
```sql
-- Payment reconciliation worker index
CREATE INDEX ix_payments_reconciliation_v33 
ON payments (status, expires_at) 
WHERE status = 'CREATED';

-- Grace period reaper worker index
CREATE INDEX ix_subscriptions_grace_reaper_v33 
ON user_subscriptions (status, grace_period_end) 
WHERE status = 'PAST_DUE';

-- Webhook execution queue index
CREATE INDEX ix_webhook_events_queue 
ON webhook_events (processed, next_retry_at) 
WHERE processed = FALSE;

-- Order creation lease audit index
CREATE INDEX ix_payments_lease_audit_v33 
ON payments (order_creation_status, order_creation_lease_expires_at) 
WHERE order_creation_status IN ('IN_PROGRESS', 'UNKNOWN');
```

---

## 19. Security and Operational Considerations

1. **HMAC Signature Verification**:
   - Webhook signatures are verified against **raw request bytes** prior to any JSON decoding using `HMAC-SHA256` and `RAZORPAY_WEBHOOK_SECRET`.
2. **Credential Sanitization**:
   - Database connection strings, Razorpay API keys, and secret keys must **never** appear in log outputs, error messages, or exception stack traces.
3. **Database Resource Protection**:
   - Connection pools are configured with `pool_size=10`, `max_overflow=20`, and `pool_pre_ping=True` to handle transient network drops on Neon Serverless PostgreSQL.
4. **Monitoring & Metric Alerts**:
   - P1 Alert: Any row entering `order_creation_status = 'ESCALATED_MANUAL'`.
   - P1 Alert: Any row in `refund_intents` remaining in `UNKNOWN` $> 30\text{ minutes}$.
   - P2 Alert: Webhook queue backlog exceeding 50 unprocessed events.

---

## 20. Business Decision Required

The following three commercial policies cannot be decided technically and require explicit stakeholder approval:

1. **Voluntary Refund Policy for Ultra Plan**:
   - *Technical Baseline*: The architecture supports full and partial automated refunds.
   - *Commercial Decision*: Is the ₹49/month Ultra plan strictly non-refundable once activated, or is a full refund permitted within a 24-hour window if zero chat/itinerary quota has been consumed?
   - *Architect Recommendation*: **Strict no-refund policy** on the ₹49 plan due to high gateway processing fees relative to ticket size, except where service outages are documented.
2. **Chargeback / Dispute Entitlement Handling**:
   - *Technical Baseline*: Razorpay emits `payment.dispute.created`.
   - *Commercial Decision*: Should Ultra access be revoked immediately upon notice of a bank chargeback, or should access continue until the arbitration window (usually 7–14 days) concludes?
   - *Architect Recommendation*: **Immediate revocation** if fraud score is elevated; otherwise, retain access and flag the account for administrative review.
3. **Late Capture Commercial Treatment**:
   - *Technical Baseline*: Late captures on cancelled/expired orders are quarantined and automatically refunded by default.
   - *Commercial Decision*: Should the user be refunded, or should the system automatically instantiate a brand-new 1-month Ultra subscription from the late capture timestamp?
   - *Architect Recommendation*: **Automatic refund**. Users who abandoned checkout may have purchased elsewhere or no longer desire the service; auto-activating without consent creates billing dispute liabilities.

---

## 21. Final Implementation Checklist

- [x] All 6 state machines defined with explicit triggers, preconditions, and transitions.
- [x] Strict separation of gateway calls from database transactions.
- [x] Global lock ordering defined and applied to prevent deadlocks.
- [x] Drift-free calendar billing calculations implemented via anchor days.
- [x] Fail-closed access guard verifying funding payment, dates, and capture validity.
- [x] Durable refund intent reservations preventing balance overages.
- [x] Two-phase webhook ingestion separating fast 200 OK from domain execution.
- [x] Approach B (`payment_attempts`) adopted with unique primary capture enforcement.
- [x] Quotas, timezone fallbacks (`Asia/Kolkata`), and 3-day grace period fully specified.
- [x] Zero application source code, models, or database tables modified.

