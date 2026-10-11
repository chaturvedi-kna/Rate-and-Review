import json
import logging
import sys
import threading
from typing import Dict, Any, List

import db
from meesho_api import validate_account, refresh_account_tokens, submit_review_full


def process_single_task(task_id: int, user_id: int, session_data: dict, service_type: str, cost: float, rating_stars: int, comments: str):
    """Executes a single review/refresh task in the background, updating DB and handling refunds on failure."""
    db.update_task_status(task_id, status="PROCESSING")
    mobile = session_data.get("mobile", "unknown")
    print(f"[Worker] >>> Starting Task #{task_id} for +91 {mobile} (Service: {service_type}, Stars: {rating_stars})", flush=True)

    # Check admin setting for telegram bot
    tg_enabled = db.get_setting("telegram_bot_enabled", "true").lower() == "true"
    allow_auto_refresh = (service_type == "auto_pilot" and tg_enabled)

    success = False
    order_id = None
    sub_order_id = None
    product_title = None
    rating_id = None
    error_msg = None

    try:
        if service_type == "refresh_only":
            if not tg_enabled:
                raise RuntimeError("Telegram token refresh service is currently disabled by administrator.")
            print(f"[Worker] [{mobile}] Refreshing tokens via Telegram bot...", flush=True)
            ref_res = refresh_account_tokens(session_data)
            if ref_res.get("success"):
                success = True
                session_data["xo"] = ref_res.get("xo")
                print(f"[Worker] [{mobile}] Tokens refreshed successfully!", flush=True)
            else:
                raise RuntimeError(ref_res.get("error", "Failed to refresh token"))

        else:
            # First validate to discover order info and session health
            print(f"[Worker] [{mobile}] Step 1: Validating account session on Meesho API...", flush=True)
            val = validate_account(session_data)

            # Check if token is expired or revoked
            if val["status"] in ("REVOKED_1007", "EXPIRED_1014", "UNAUTHORIZED_401"):
                if service_type == "standard_review":
                    raise RuntimeError(
                        f"Account session token is expired or revoked ({val['status']}). "
                        "Since 'Fresh Accounts (Instant Review)' was chosen, expired tokens cannot be processed directly. "
                        "Please select 'Old Accounts (Auto-Refresh & Review)' to auto-refresh it, or paste fresh JSONs."
                    )
                elif allow_auto_refresh:
                    print(f"[Worker] [{mobile}] Session is {val['status']}. Triggering Telegram auto-refresh...", flush=True)
                    ref_res = refresh_account_tokens(session_data)
                    if not ref_res.get("success"):
                        raise RuntimeError(f"Auto-pilot token refresh failed: {ref_res.get('error')}. Telegram bot may be offline or session credentials invalid.")
                    session_data["xo"] = ref_res.get("xo")
                    print(f"[Worker] [{mobile}] Token refreshed! Re-validating...", flush=True)
                    val = validate_account(session_data)
                else:
                    raise RuntimeError(f"Account session token is expired or revoked ({val['status']}), and auto-refresh is disabled.")

            if not val.get("valid"):
                raise RuntimeError(val.get("error") or "Account session could not be authenticated on Meesho.")

            ratable = val.get("ratable_order") or {}
            order_id = str(ratable.get("order_id") or "")
            sub_order_id = str(ratable.get("sub_order_id") or "")
            product_title = ratable.get("title") or "Meesho Order"

            if not order_id and val.get("order_count", 0) == 0:
                raise RuntimeError("No orders found in this Meesho account. Account must have at least one purchase to write a review.")

            print(f"[Worker] [{mobile}] Step 2: Target order identified: #{order_id} (Product: {product_title}). Submitting 11-step review...", flush=True)

            # Submit 11-step real review
            rev_res = submit_review_full(
                session_data,
                rating_stars=rating_stars,
                comments_text=comments,
                auto_refresh=allow_auto_refresh,
            )

            if rev_res.get("success"):
                success = True
                order_id = str(rev_res.get("order_id") or order_id)
                sub_order_id = str(rev_res.get("sub_order_id") or sub_order_id)
                rating_id = str(rev_res.get("rating_id") or "")
                print(f"[Worker] <<< Task #{task_id} COMPLETED for +91 {mobile}! Order #{order_id}, Rating ID: {rating_id}", flush=True)
            else:
                raise RuntimeError(rev_res.get("error", "Review submission failed"))

    except Exception as exc:
        success = False
        error_msg = str(exc)
        print(f"[Worker] [X] Task #{task_id} FAILED for +91 {mobile}: {error_msg}. Refunding ₹{cost:.2f} to User #{user_id}", flush=True)
        import traceback
        traceback.print_exc()
        sys.stdout.flush()

    if success:
        db.update_task_status(
            task_id,
            status="COMPLETED",
            order_id=order_id,
            sub_order_id=sub_order_id,
            product_title=product_title,
            rating_id=rating_id,
        )
    else:
        # Mark as failed and refund the user's wallet
        db.update_task_status(task_id, status="FAILED", error=error_msg)
        db.update_user_balance(
            user_id=user_id,
            delta=cost,
            tx_type="REFUND",
            notes=f"Automatic refund for failed task #{task_id}: {error_msg[:100]}",
        )
        print(f"[Worker] Task #{task_id} refund of ₹{cost:.2f} credited back to User #{user_id} wallet.", flush=True)


import reviews_dataset


def dispatch_batch_tasks(
    user_id: int,
    accounts: List[dict],
    service_type: str,
    rating_mode: Any = "5",
    review_mode: str = "auto",
    custom_comments: str = "",
) -> Dict[str, Any]:
    """
    Validates wallet funds and token expiry, creates task records in DB, deducts cost, and triggers processing.
    """
    # Backwards compatibility if called with (user_id, accounts, service_type, rating_stars, comments)
    if isinstance(rating_mode, int) or (isinstance(rating_mode, str) and str(rating_mode).isdigit() and review_mode not in ("auto", "custom")):
        if review_mode not in ("auto", "custom"):
            custom_comments = review_mode
            review_mode = "custom" if custom_comments.strip() else "auto"
            rating_mode = str(rating_mode)

    # If service is 'standard_review', verify that no expired tokens were passed
    if service_type == "standard_review":
        expired = [a for a in accounts if a.get("is_expired")]
        if expired:
            mobiles_str = ", ".join(f"+91 {a['mobile']}" for a in expired[:3])
            more = f" and {len(expired)-3} more" if len(expired) > 3 else ""
            return {
                "success": False,
                "error": (
                    f"Expired session token detected for {mobiles_str}{more}. "
                    "Since you selected 'Fresh Accounts (Instant Review)', expired sessions cannot be processed directly. "
                    "Please select 'Old Accounts (Auto-Refresh & Review)' to automatically refresh your session tokens, or generate and paste fresh JSONs."
                ),
            }

    # Determine cost per service from DB settings
    if service_type == "auto_pilot":
        price_per_item = float(db.get_setting("price_auto_pilot", "10.0"))
        service_label = "Old Accounts (Auto-Refresh & Review)"
    else:
        price_per_item = float(db.get_setting("price_standard_review", "7.0"))
        service_label = "Fresh Accounts (Instant Review)"

    total_cost = len(accounts) * price_per_item
    user = db.get_user_by_id(user_id)
    if not user:
        return {"success": False, "error": "User not found"}

    if user["wallet_balance"] < total_cost:
        needed = total_cost - user["wallet_balance"]
        return {
            "success": False,
            "error": (
                f"Insufficient wallet balance! You submitted {len(accounts)} account(s) costing ₹{total_cost:.2f} "
                f"(₹{price_per_item:.2f}/item for {service_label}), but your wallet balance is ₹{user['wallet_balance']:.2f}. "
                f"Please add ₹{needed:.2f} in your Wallet via UPI to proceed."
            ),
        }

    # Deduct wallet balance
    ok = db.update_user_balance(
        user_id=user_id,
        delta=-total_cost,
        tx_type="REVIEW_CHARGE",
        notes=f"Order review batch: {len(accounts)} accounts ({service_type})",
    )
    if not ok:
        return {"success": False, "error": "Transaction could not be processed due to insufficient balance."}

    created_task_ids = []
    for acc in accounts:
        mobile = acc.get("mobile", "")
        raw_json_str = json.dumps(acc)

        # Resolve rating and comment for this specific task
        task_stars, task_comments = reviews_dataset.resolve_rating_and_comment(
            rating_mode=rating_mode,
            review_mode=review_mode,
            custom_comment=custom_comments,
        )

        t_id = db.create_task(
            user_id=user_id,
            mobile=mobile,
            service_type=service_type,
            cost=price_per_item,
            rating_stars=task_stars,
            comments=task_comments,
            raw_json=raw_json_str,
        )
        created_task_ids.append(t_id)

        # Launch worker thread
        t = threading.Thread(
            target=process_single_task,
            args=(t_id, user_id, acc, service_type, price_per_item, task_stars, task_comments),
            daemon=True,
        )
        t.start()

    return {
        "success": True,
        "task_count": len(created_task_ids),
        "total_cost": total_cost,
        "task_ids": created_task_ids,
    }

