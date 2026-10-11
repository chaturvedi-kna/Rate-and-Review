from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Dict, Any, List

from flask import (
    Flask,
    request,
    jsonify,
    render_template_string,
    session,
    redirect,
    url_for,
    flash,
)

import db
from account_parser import parse_multi_jsons
from worker import dispatch_batch_tasks
import famgateway_client

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "meesho-studio-secret-key-2026-safe")


# ------------------------------------------------------------
# Authentication Decorators
# ------------------------------------------------------------
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login_page"))
        user = db.get_user_by_id(session["user_id"])
        if not user or user["role"] != "admin":
            flash("Admin access required.", "error")
            return redirect(url_for("dashboard_page"))
        return f(*args, **kwargs)
    return decorated_function


# ------------------------------------------------------------
# Templates
# ------------------------------------------------------------
BASE_NAV = """
<header class="border-b border-slate-800 bg-slate-900/90 backdrop-blur sticky top-0 z-50">
  <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
    <div class="flex items-center space-x-3">
      <a href="/" class="flex items-center gap-3 group">
        <div class="h-10 w-10 rounded-xl bg-gradient-to-tr from-fuchsia-600 to-pink-500 flex items-center justify-center shadow-lg shadow-pink-500/20 group-hover:scale-105 transition-transform">
          <i class="fa-solid fa-star text-white text-lg"></i>
        </div>
        <div>
          <h1 class="text-base font-bold text-white tracking-tight flex items-center gap-2">
            Meesho Studio
            {% if session.role == 'admin' %}
            <span class="text-[10px] font-bold px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/20">ADMIN</span>
            {% else %}
            <span class="text-[10px] font-medium px-2 py-0.5 rounded-full bg-pink-500/10 text-pink-400 border border-pink-500/20">CLIENT</span>
            {% endif %}
          </h1>
          <p class="text-[11px] text-slate-400">Automated Reviews & Account Manager</p>
        </div>
      </a>
    </div>
    
    <div class="flex items-center gap-3">
      <!-- Wallet Pill -->
      <a href="/wallet" class="flex items-center gap-2 bg-slate-800/90 hover:bg-slate-700/80 px-3.5 py-1.5 rounded-xl border border-slate-700 transition">
        <i class="fa-solid fa-wallet text-emerald-400 text-sm"></i>
        <span class="text-xs text-slate-300">Balance: <strong class="text-emerald-400 font-mono">₹{{ "%.2f"|format(user.wallet_balance) }}</strong></span>
        <span class="text-[10px] bg-emerald-500/20 text-emerald-300 px-1.5 py-0.5 rounded ml-1 font-semibold">+ Top Up</span>
      </a>

      {% if session.role == 'admin' %}
      <a href="/admin" class="text-xs bg-amber-500/10 text-amber-300 hover:bg-amber-500/20 px-3 py-1.5 rounded-xl border border-amber-500/30 transition flex items-center gap-1.5 font-medium">
        <i class="fa-solid fa-shield-halved"></i> Admin Panel
      </a>
      {% endif %}

      <div class="h-4 w-px bg-slate-800 mx-1"></div>

      <!-- Password Change Button -->
      <button onclick="openPasswordModal()" title="Change Password" class="text-xs text-slate-300 hover:text-white px-2.5 py-1.5 rounded-lg hover:bg-slate-800 transition flex items-center gap-1.5">
        <i class="fa-solid fa-key text-slate-400"></i>
        <span class="hidden sm:inline">{{ user.username }}</span>
      </button>

      <a href="/logout" title="Sign Out" class="text-xs text-slate-400 hover:text-red-400 p-2 rounded-lg hover:bg-slate-800 transition">
        <i class="fa-solid fa-right-from-bracket"></i>
      </a>
    </div>
  </div>
</header>

<!-- Change Password Modal -->
<div id="password-modal" class="hidden fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
  <div class="bg-slate-900 border border-slate-800 rounded-2xl max-w-sm w-full p-6 space-y-4 shadow-2xl">
    <div class="flex items-center justify-between">
      <h4 class="text-sm font-semibold text-white flex items-center gap-2">
        <i class="fa-solid fa-key text-pink-500"></i> Change Account Password
      </h4>
      <button onclick="closePasswordModal()" class="text-slate-400 hover:text-white"><i class="fa-solid fa-xmark"></i></button>
    </div>
    <form onsubmit="handlePasswordChange(event)" class="space-y-3">
      <div>
        <label class="block text-[11px] text-slate-400 mb-1">Current Password:</label>
        <input type="password" id="old-pass" required class="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-xs text-white focus:outline-none focus:border-pink-500">
      </div>
      <div>
        <label class="block text-[11px] text-slate-400 mb-1">New Password:</label>
        <input type="password" id="new-pass" required minlength="6" class="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-xs text-white focus:outline-none focus:border-pink-500">
      </div>
      <div>
        <label class="block text-[11px] text-slate-400 mb-1">Confirm New Password:</label>
        <input type="password" id="confirm-pass" required minlength="6" class="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-xs text-white focus:outline-none focus:border-pink-500">
      </div>
      <button type="submit" id="btn-save-pass" class="w-full bg-pink-600 hover:bg-pink-500 text-white font-medium text-xs py-2.5 rounded-xl transition">
        Update Password
      </button>
    </form>
  </div>
</div>

<script>
  function openPasswordModal() { document.getElementById('password-modal').classList.remove('hidden'); }
  function closePasswordModal() { document.getElementById('password-modal').classList.add('hidden'); }
  async function handlePasswordChange(e) {
    e.preventDefault();
    const oldP = document.getElementById('old-pass').value;
    const newP = document.getElementById('new-pass').value;
    const confP = document.getElementById('confirm-pass').value;
    if (newP !== confP) { alert("New passwords do not match!"); return; }

    const res = await fetch('/api/change_password', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ current_password: oldP, new_password: newP })
    });
    const d = await res.json();
    if (d.success) {
      alert("Password updated successfully!");
      closePasswordModal();
    } else {
      alert(d.error || "Failed to update password");
    }
  }
</script>
"""

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Dashboard - Meesho Automation Studio</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
    body { font-family: 'Inter', sans-serif; }
    .font-mono { font-family: 'JetBrains Mono', monospace; }
  </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen flex flex-col">
  """ + BASE_NAV + """

  <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 flex-1 w-full space-y-6">

    <!-- User Metrics Row -->
    <div class="grid grid-cols-2 sm:grid-cols-4 gap-4">
      <div class="bg-slate-900/70 border border-slate-800 rounded-2xl p-4 flex items-center justify-between">
        <div>
          <p class="text-xs text-slate-400 font-medium">Orders Submitted</p>
          <p class="text-2xl font-bold text-white mt-1">{{ stats.submitted }}</p>
        </div>
        <div class="h-10 w-10 rounded-xl bg-blue-500/10 text-blue-400 flex items-center justify-center text-lg">
          <i class="fa-solid fa-paper-plane"></i>
        </div>
      </div>

      <div class="bg-slate-900/70 border border-slate-800 rounded-2xl p-4 flex items-center justify-between">
        <div>
          <p class="text-xs text-emerald-400 font-medium">Reviewed & Completed</p>
          <p class="text-2xl font-bold text-emerald-400 mt-1">{{ stats.completed }}</p>
        </div>
        <div class="h-10 w-10 rounded-xl bg-emerald-500/10 text-emerald-400 flex items-center justify-center text-lg">
          <i class="fa-solid fa-circle-check"></i>
        </div>
      </div>

      <div class="bg-slate-900/70 border border-slate-800 rounded-2xl p-4 flex items-center justify-between">
        <div>
          <p class="text-xs text-amber-400 font-medium">In Progress / Pending</p>
          <p class="text-2xl font-bold text-amber-400 mt-1">{{ stats.pending }}</p>
        </div>
        <div class="h-10 w-10 rounded-xl bg-amber-500/10 text-amber-400 flex items-center justify-center text-lg">
          <i class="fa-solid fa-clock-rotate-left"></i>
        </div>
      </div>

      <div class="bg-slate-900/70 border border-slate-800 rounded-2xl p-4 flex items-center justify-between">
        <div>
          <p class="text-xs text-red-400 font-medium">Failed (Refunded)</p>
          <p class="text-2xl font-bold text-red-400 mt-1">{{ stats.failed }}</p>
        </div>
        <div class="h-10 w-10 rounded-xl bg-red-500/10 text-red-400 flex items-center justify-center text-lg">
          <i class="fa-solid fa-arrow-rotate-left"></i>
        </div>
      </div>
    </div>

    <!-- Submit Review Section -->
    <div class="bg-slate-900/80 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-5">
      <div class="flex items-center justify-between border-b border-slate-800 pb-3">
        <div>
          <h2 class="text-base font-bold text-white flex items-center gap-2">
            <i class="fa-solid fa-plus-circle text-pink-500"></i>
            Submit Orders for Review
          </h2>
          <p class="text-xs text-slate-400">Upload or paste your account JSONs. Ratings and reviews are processed automatically.</p>
        </div>
        <button onclick="loadSample()" class="text-xs text-pink-400 hover:text-pink-300 font-medium hover:underline">
          Load Sample Accounts
        </button>
      </div>

      <form id="submit-form" onsubmit="handleJobSubmit(event)" class="space-y-4">
        <!-- Textarea for any JSON format -->
        <div>
          <label class="block text-xs font-semibold text-slate-300 mb-1.5">Account JSON(s) Input:</label>
          <textarea id="json-input" rows="6" required placeholder='Paste single JSON, JSON Array, or multiple JSONs separated by space/newline...&#10;{"mobile": "8869049741", "xo": "eyJ..."}&#10;{"mobile": "7977748514", "xo": "eyJ..."}' class="w-full bg-slate-950 border border-slate-800 rounded-xl p-3.5 text-xs font-mono text-slate-200 focus:outline-none focus:border-pink-500 transition resize-none"></textarea>
          <p class="text-[11px] text-slate-500 mt-1">Accepts any format (Single, Array <code>[{...}]</code>, or space-separated). Only mobile and token required.</p>
        </div>

        <!-- 2 Simplified Service Levels -->
        <div>
          <label class="block text-xs font-semibold text-slate-300 mb-2">Select Service Level:</label>
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
            <label class="cursor-pointer border border-pink-500/40 bg-pink-500/10 hover:bg-pink-500/15 rounded-xl p-4 flex items-start space-x-3 transition">
              <input type="radio" name="service_type" value="auto_pilot" checked class="mt-1 text-pink-600 focus:ring-0">
              <div>
                <p class="text-xs font-bold text-pink-300 flex items-center justify-between">
                  🚀 Old Accounts (Auto-Refresh & Review)
                  <span class="text-emerald-400 font-mono ml-2">₹{{ prices.price_auto_pilot }}/order</span>
                </p>
                <p class="text-[11px] text-slate-400 mt-1">Recommended for older accounts. Automatically refreshes expired session tokens and publishes product rating and review.</p>
              </div>
            </label>

            <label class="cursor-pointer border border-slate-800 bg-slate-950/70 hover:border-slate-700 rounded-xl p-4 flex items-start space-x-3 transition">
              <input type="radio" name="service_type" value="standard_review" class="mt-1 text-pink-600 focus:ring-0">
              <div>
                <p class="text-xs font-bold text-white flex items-center justify-between">
                  ⚡ Fresh Accounts (Instant Review)
                  <span class="text-emerald-400 font-mono ml-2">₹{{ prices.price_standard_review }}/order</span>
                </p>
                <p class="text-[11px] text-slate-400 mt-1">Recommended for newly generated or fresh logged-in accounts. Directly submits product rating and review.</p>
              </div>
            </label>
          </div>
        </div>

        <!-- Rating Mode & Review Feedback Options -->
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4 bg-slate-950/60 border border-slate-800 rounded-xl p-4">
          <!-- Star Rating Mode -->
          <div>
            <label class="block text-xs font-semibold text-slate-300 mb-1.5 flex items-center justify-between">
              <span>Star Rating Mode:</span>
              <span class="text-[11px] text-pink-400 font-normal">Choose review stars</span>
            </label>
            <select id="rating-mode" class="w-full bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-xs text-amber-400 font-semibold focus:outline-none focus:border-pink-500">
              <option value="5" selected>★★★★★ 5 Stars Only (All 5★)</option>
              <option value="combo_4_5">★ 4 & 5 Stars Combo (~75% 5★ & ~25% 4★ Natural Mix)</option>
              <option value="4">★★★★☆ 4 Stars Only (All 4★)</option>
            </select>
            <p class="text-[11px] text-slate-500 mt-1">"Combo 4 & 5" distributes ratings organically to look authentic to algorithms.</p>
          </div>

          <!-- Review Comments Content Mode -->
          <div>
            <label class="block text-xs font-semibold text-slate-300 mb-1.5 flex items-center justify-between">
              <span>Review Text Content:</span>
              <span class="text-[11px] text-emerald-400 font-normal">300+ Verified Pool</span>
            </label>
            <div class="space-y-2">
              <div class="flex items-center gap-4 text-xs">
                <label class="inline-flex items-center gap-1.5 cursor-pointer text-slate-200">
                  <input type="radio" name="review_mode" value="auto" checked onchange="toggleReviewMode()" class="text-pink-600 focus:ring-0">
                  <span>Auto Realistic Pool (300+ Reviews)</span>
                </label>
                <label class="inline-flex items-center gap-1.5 cursor-pointer text-slate-200">
                  <input type="radio" name="review_mode" value="custom" onchange="toggleReviewMode()" class="text-pink-600 focus:ring-0">
                  <span>Custom Text</span>
                </label>
              </div>

              <div id="custom-review-container" class="hidden">
                <input type="text" id="review-comments" placeholder="e.g. Very good quality, fabric is soft and comfortable. Value for money!" class="w-full bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-pink-500" value="Very good quality, fabric is soft and comfortable. Value for money!">
              </div>
              <div id="auto-review-badge" class="bg-slate-900/80 border border-slate-800 rounded-lg p-2 text-[11px] text-slate-400 flex items-center gap-2">
                <i class="fa-solid fa-wand-magic-sparkles text-pink-400 text-xs"></i>
                <span>Orders will automatically rotate across 300+ authentic, diverse e-commerce reviews for highest authenticity.</span>
              </div>
            </div>
          </div>
        </div>

        <div class="flex items-center justify-between pt-2">
          <p id="cost-estimate" class="text-xs text-slate-400 font-mono">
            Wallet Balance: <strong class="text-emerald-400">₹{{ "%.2f"|format(user.wallet_balance) }}</strong>
          </p>
          <button type="submit" id="btn-submit" class="bg-gradient-to-r from-pink-600 to-fuchsia-600 hover:from-pink-500 hover:to-fuchsia-500 text-white font-medium text-xs py-2.5 px-6 rounded-xl shadow-lg shadow-pink-600/20 transition flex items-center gap-2">
            <i class="fa-solid fa-play"></i>
            Submit & Start Reviewing
          </button>
        </div>
      </form>
    </div>

    <!-- Review Tasks History -->
    <div class="bg-slate-900/80 border border-slate-800 rounded-2xl overflow-hidden shadow-xl">
      <div class="px-6 py-4 border-b border-slate-800 flex items-center justify-between bg-slate-900">
        <h3 class="text-sm font-semibold text-white flex items-center gap-2">
          <i class="fa-solid fa-list-check text-pink-500"></i>
          Your Review Submissions History
        </h3>
        <button onclick="location.reload()" class="text-xs text-slate-400 hover:text-white transition">
          <i class="fa-solid fa-rotate-right mr-1"></i> Refresh
        </button>
      </div>

      <div class="overflow-x-auto">
        <table class="w-full text-left text-xs border-collapse">
          <thead>
            <tr class="border-b border-slate-800 text-slate-400 bg-slate-950/40">
              <th class="p-3.5">Account Phone</th>
              <th class="p-3.5">Product / Order</th>
              <th class="p-3.5">Service</th>
              <th class="p-3.5">Rating & Feedback</th>
              <th class="p-3.5">Cost</th>
              <th class="p-3.5">Status</th>
              <th class="p-3.5 text-right">Submitted At</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-800/60 font-sans">
            {% if tasks %}
              {% for t in tasks %}
              <tr class="hover:bg-slate-900/40 transition">
                <td class="p-3.5 font-mono font-medium text-white">+91 {{ t.mobile }}</td>
                <td class="p-3.5">
                  {% if t.order_id %}
                    <span class="text-slate-200 font-medium">{{ t.product_title or 'Meesho Order' }}</span>
                    <span class="text-[10px] text-slate-400 block font-mono">Order #{{ t.order_id }}</span>
                  {% else %}
                    <span class="text-slate-500">-</span>
                  {% endif %}
                </td>
                <td class="p-3.5">
                  {% if t.service_type == 'auto_pilot' %}
                    <span class="px-2 py-0.5 rounded text-[10px] bg-pink-500/10 text-pink-400 border border-pink-500/20">Auto-Refresh & Review</span>
                  {% else %}
                    <span class="px-2 py-0.5 rounded text-[10px] bg-blue-500/10 text-blue-400 border border-blue-500/20">Instant Review</span>
                  {% endif %}
                </td>
                <td class="p-3.5">
                  {% if t.status == 'COMPLETED' %}
                    <span class="text-amber-400 font-semibold">{{ t.rating_stars }}★</span>
                    <span class="text-slate-300 text-[11px] block truncate max-w-xs" title="{{ t.comments }}">{{ t.comments }}</span>
                  {% elif t.status == 'FAILED' %}
                    <span class="text-red-400 text-[11px]" title="{{ t.error_message }}">{{ t.error_message[:45] }}...</span>
                  {% else %}
                    <span class="text-slate-500">-</span>
                  {% endif %}
                </td>
                <td class="p-3.5 font-mono text-emerald-400">₹{{ "%.2f"|format(t.cost) }}</td>
                <td class="p-3.5">
                  {% if t.status == 'COMPLETED' %}
                    <span class="px-2.5 py-1 rounded-full text-[10px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                      <i class="fa-solid fa-check mr-1"></i> Completed
                    </span>
                  {% elif t.status == 'PROCESSING' %}
                    <span class="px-2.5 py-1 rounded-full text-[10px] font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/20 animate-pulse">
                      <i class="fa-solid fa-spinner fa-spin mr-1"></i> Reviewing
                    </span>
                  {% elif t.status == 'FAILED' %}
                    <span class="px-2.5 py-1 rounded-full text-[10px] font-semibold bg-red-500/10 text-red-400 border border-red-500/20" title="{{ t.error_message }}">
                      <i class="fa-solid fa-xmark mr-1"></i> Failed (Refunded)
                    </span>
                  {% else %}
                    <span class="px-2.5 py-1 rounded-full text-[10px] font-semibold bg-slate-800 text-slate-400 border border-slate-700">
                      Pending
                    </span>
                  {% endif %}
                </td>
                <td class="p-3.5 text-right text-slate-400 text-[11px] font-mono">{{ t.created_at[:16].replace('T', ' ') }}</td>
              </tr>
              {% endfor %}
            {% else %}
              <tr>
                <td colspan="7" class="p-8 text-center text-slate-500">
                  No review submissions yet. Paste your accounts above to begin!
                </td>
              </tr>
            {% endif %}
          </tbody>
        </table>
      </div>
    </div>

  </main>

  <script>
    async function loadSample() {
      try {
        const res = await fetch('/api/sample');
        const data = await res.json();
        document.getElementById('json-input').value = JSON.stringify(data, null, 2);
      } catch (e) {
        alert("Failed to load sample: " + e.message);
      }
    }

    function toggleReviewMode() {
      const mode = document.querySelector('input[name="review_mode"]:checked').value;
      const customBox = document.getElementById('custom-review-container');
      const autoBadge = document.getElementById('auto-review-badge');
      if (mode === 'custom') {
        customBox.classList.remove('hidden');
        autoBadge.classList.add('hidden');
      } else {
        customBox.classList.add('hidden');
        autoBadge.classList.remove('hidden');
      }
    }

    async function handleJobSubmit(e) {
      e.preventDefault();
      const rawText = document.getElementById('json-input').value.trim();
      const serviceType = document.querySelector('input[name="service_type"]:checked').value;
      const ratingMode = document.getElementById('rating-mode').value;
      const reviewMode = document.querySelector('input[name="review_mode"]:checked').value;
      const comments = document.getElementById('review-comments').value.trim();

      const btn = document.getElementById('btn-submit');
      btn.disabled = true;
      btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Processing...';

      try {
        const res = await fetch('/api/submit_jobs', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            raw_text: rawText,
            service_type: serviceType,
            rating_mode: ratingMode,
            review_mode: reviewMode,
            comments: comments
          })
        });
        const data = await res.json();
        if (data.success) {
          alert(`Successfully scheduled ${data.task_count} review task(s)! Total deducted: ₹${data.total_cost.toFixed(2)}`);
          location.reload();
        } else {
          alert(data.error || "Submission failed.");
          btn.disabled = false;
          btn.innerHTML = '<i class="fa-solid fa-play"></i> Submit & Start Reviewing';
        }
      } catch (err) {
        alert("Error: " + err.message);
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-play"></i> Submit & Start Reviewing';
      }
    }
  </script>
</body>
</html>
"""

WALLET_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Wallet & Top Up - Meesho Automation Studio</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
    body { font-family: 'Inter', sans-serif; }
    .font-mono { font-family: 'JetBrains Mono', monospace; }
  </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen flex flex-col">
  """ + BASE_NAV + """

  <main class="max-w-4xl mx-auto px-4 sm:px-6 py-8 flex-1 w-full space-y-8">

    {% with messages = get_flashed_messages(with_categories=true) %}
      {% if messages %}
        {% for category, message in messages %}
          <div class="p-3.5 rounded-2xl text-xs flex items-center gap-2.5 {% if category == 'error' %}bg-red-500/10 text-red-400 border border-red-500/20{% else %}bg-emerald-500/10 text-emerald-400 border border-emerald-500/20{% endif %}">
            <i class="fa-solid {% if category == 'error' %}fa-circle-exclamation text-red-400{% else %}fa-circle-check text-emerald-400{% endif %}"></i>
            <span>{{ message }}</span>
          </div>
        {% endfor %}
      {% endif %}
    {% endwith %}

    <!-- Wallet Balance Overview -->
    <div class="bg-gradient-to-r from-slate-900 to-slate-900/90 border border-slate-800 rounded-3xl p-6 sm:p-8 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 shadow-2xl">
      <div>
        <span class="text-xs font-semibold uppercase tracking-wider text-slate-400">Your Current Balance</span>
        <h2 class="text-3xl sm:text-4xl font-extrabold text-emerald-400 font-mono mt-1">₹{{ "%.2f"|format(user.wallet_balance) }}</h2>
        <p class="text-xs text-slate-400 mt-1">Funds are deducted automatically when starting reviews and refunded if any task fails.</p>
      </div>
      <a href="#payment-section" class="bg-emerald-600 hover:bg-emerald-500 text-white font-medium text-xs px-5 py-3 rounded-xl shadow-lg shadow-emerald-600/20 transition flex items-center gap-2">
        <i class="fa-solid fa-arrow-down"></i> Add Funds via UPI
      </a>
    </div>

    <!-- UPI Top-up Section (Automated Primary + Manual Fallback) -->
    <div id="payment-section" class="bg-slate-900/90 border border-slate-800 rounded-3xl p-6 sm:p-8 shadow-xl space-y-6">
      <div class="border-b border-slate-800 pb-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h3 class="text-lg font-bold text-white flex items-center gap-2">
            <i class="fa-solid fa-wallet text-pink-500"></i>
            Add Funds to Wallet
          </h3>
          <p class="text-xs text-slate-400">
            Minimum top-up: <strong class="text-emerald-400 font-mono">₹{{ settings.min_topup_amount }}</strong>. Fast & secure UPI payment.
          </p>
        </div>
        <!-- Method Selector Pills -->
        <div class="inline-flex p-1 bg-slate-950 border border-slate-800 rounded-xl text-xs shrink-0">
          <button type="button" id="tab-auto" onclick="switchTopupMethod('auto')" class="px-3.5 py-1.5 rounded-lg font-semibold transition bg-pink-600 text-white shadow">
            ⚡ Instant Auto UPI
          </button>
          <button type="button" id="tab-manual" onclick="switchTopupMethod('manual')" class="px-3.5 py-1.5 rounded-lg font-medium transition text-slate-400 hover:text-white">
            📝 Manual Transfer
          </button>
        </div>
      </div>

      <!-- Option 1: Instant Automated Checkout (Default & Recommended) -->
      <div id="section-auto-topup" class="space-y-5">
        <div class="bg-pink-500/10 border border-pink-500/20 rounded-2xl p-4 flex items-start gap-3">
          <div class="h-9 w-9 rounded-xl bg-pink-500/20 text-pink-400 flex items-center justify-center shrink-0 mt-0.5">
            <i class="fa-solid fa-bolt text-sm"></i>
          </div>
          <div>
            <h4 class="text-xs font-bold text-pink-300">Instant Automated UPI Payment</h4>
            <p class="text-[11px] text-slate-300 mt-0.5">Pay using any UPI app (GPay, PhonePe, Paytm, CRED). Your wallet balance is credited automatically the instant payment completes.</p>
          </div>
        </div>

        <div>
          <label class="block text-xs font-semibold text-slate-300 mb-1.5">Enter Amount to Add (₹):</label>
          <div class="relative max-w-md">
            <span class="absolute left-3.5 top-2.5 text-xs text-slate-400 font-mono font-bold">₹</span>
            <input type="number" id="auto-deposit-amount" min="{{ settings.min_topup_amount }}" step="1" required value="{{ settings.min_topup_amount }}" class="w-full bg-slate-950 border border-slate-800 rounded-xl pl-8 pr-3.5 py-2.5 text-sm font-mono text-emerald-400 focus:outline-none focus:border-pink-500">
          </div>
          <div class="flex flex-wrap gap-2 mt-2">
            <button type="button" onclick="setAutoAmount(50)" class="text-xs bg-slate-950 hover:bg-slate-800 text-slate-300 px-3 py-1.5 rounded-lg border border-slate-800 transition">₹50</button>
            <button type="button" onclick="setAutoAmount(100)" class="text-xs bg-slate-950 hover:bg-slate-800 text-slate-300 px-3 py-1.5 rounded-lg border border-slate-800 transition">₹100</button>
            <button type="button" onclick="setAutoAmount(250)" class="text-xs bg-slate-950 hover:bg-slate-800 text-slate-300 px-3 py-1.5 rounded-lg border border-slate-800 transition">₹250</button>
            <button type="button" onclick="setAutoAmount(500)" class="text-xs bg-slate-950 hover:bg-slate-800 text-slate-300 px-3 py-1.5 rounded-lg border border-slate-800 transition">₹500</button>
          </div>
        </div>

        <button type="button" onclick="payWithFamGateway()" id="btn-famgateway" class="w-full max-w-md bg-gradient-to-r from-pink-600 to-fuchsia-600 hover:from-pink-500 hover:to-fuchsia-500 text-white font-semibold text-xs py-3.5 rounded-xl shadow-lg shadow-pink-600/25 transition flex items-center justify-center gap-2">
          <i class="fa-solid fa-bolt"></i>
          Proceed to Instant UPI Checkout
        </button>

        <div class="pt-3 border-t border-slate-800/80">
          <p class="text-[11px] text-slate-400 flex items-center gap-2">
            <i class="fa-solid fa-circle-info text-amber-400"></i>
            <span>If automated checkout is down or having gateway issues,
              <button type="button" onclick="switchTopupMethod('manual')" class="text-pink-400 hover:text-pink-300 underline font-semibold ml-1">click here for Manual UPI Transfer</button>.
            </span>
          </p>
        </div>
      </div>

      <!-- Option 2: Manual UPI Transfer (Hidden until clicked) -->
      <div id="section-manual-topup" class="hidden space-y-6 pt-1">
        <div class="bg-amber-500/10 border border-amber-500/20 rounded-2xl p-4 flex items-start gap-3">
          <div class="h-9 w-9 rounded-xl bg-amber-500/20 text-amber-400 flex items-center justify-center shrink-0 mt-0.5">
            <i class="fa-solid fa-hand-holding-dollar text-sm"></i>
          </div>
          <div>
            <h4 class="text-xs font-bold text-amber-300">Manual UPI Transfer (Fallback)</h4>
            <p class="text-[11px] text-slate-300 mt-0.5">Transfer directly to the UPI ID or scan the QR below, then enter your 12-digit UTR reference number for confirmation.</p>
          </div>
        </div>

          <div class="grid grid-cols-1 md:grid-cols-12 gap-8 items-center">
            <!-- QR Code Display -->
            <div class="md:col-span-5 flex flex-col items-center justify-center p-6 bg-slate-950 border border-slate-800 rounded-2xl">
              <img id="qr-img" src="https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=upi://pay?pa={{ settings.upi_id }}%26pn={{ settings.upi_name|default('Meesho')|replace(' ', '%20') }}%26cu=INR" alt="UPI QR" class="w-48 h-48 rounded-xl bg-white p-2">
              <p class="text-[11px] text-slate-400 mt-3 font-medium text-center">Scan with any UPI App (GPay, PhonePe, Paytm)</p>
            </div>

            <!-- Manual Form -->
            <div class="md:col-span-7 space-y-4">
              <div class="bg-slate-950/70 border border-slate-800 p-4 rounded-xl space-y-2">
                <span class="text-[11px] text-slate-400 block font-medium">Receiver UPI ID:</span>
                <div class="flex items-center justify-between">
                  <span id="upi-id-text" class="text-sm font-mono text-pink-400 font-bold">{{ settings.upi_id }}</span>
                  <button type="button" onclick="copyUPI()" class="text-xs bg-slate-800 hover:bg-slate-700 text-slate-200 px-2.5 py-1 rounded-lg border border-slate-700 transition cursor-pointer">
                    <i class="fa-regular fa-copy mr-1"></i> Copy
                  </button>
                </div>
                <span class="text-[10px] text-slate-500 block">Name: {{ settings.upi_name }}</span>
              </div>

              <form id="manual-topup-form" onsubmit="handleManualTopupSubmit(event)" class="space-y-3.5">
                <div>
                  <label class="block text-xs font-semibold text-slate-300 mb-1">Transferred Amount (₹):</label>
                  <input type="number" id="manual-deposit-amount" min="{{ settings.min_topup_amount }}" step="1" required value="{{ settings.min_topup_amount }}" class="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2 text-xs font-mono text-emerald-400 focus:outline-none focus:border-pink-500">
                </div>

                <div>
                  <label class="block text-xs font-semibold text-slate-300 mb-1">12-Digit UPI UTR Reference Number:</label>
                  <input type="text" id="manual-deposit-utr" required placeholder="e.g. 428190348123" class="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2 text-xs font-mono text-slate-200 focus:outline-none focus:border-pink-500">
                  <p class="text-[10px] text-slate-500 mt-0.5">Found in your payment receipt inside GPay, PhonePe, or Paytm.</p>
                </div>

                <button type="submit" id="btn-manual-deposit" class="w-full bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 font-medium text-xs py-2.5 rounded-xl transition flex items-center justify-center gap-2 cursor-pointer">
                  <i class="fa-solid fa-receipt"></i>
                  Submit UTR for Verification
                </button>
              </form>
            </div>
          </div>

          <div class="text-center pt-1">
            <button type="button" onclick="switchTopupMethod('auto')" class="text-xs text-slate-400 hover:text-white transition cursor-pointer">
              &larr; Back to Instant Automated UPI
            </button>
          </div>
        </div>
      </div>

      <!-- Transaction History Table -->
      <div class="bg-slate-900/80 border border-slate-800 rounded-3xl overflow-hidden shadow-xl">
        <div class="px-6 py-4 border-b border-slate-800 bg-slate-900">
          <h4 class="text-sm font-semibold text-white">Wallet Transactions History</h4>
        </div>
        <div class="overflow-x-auto">
          <table class="w-full text-left text-xs border-collapse font-sans">
            <thead>
              <tr class="border-b border-slate-800 text-slate-400 bg-slate-950/40">
                <th class="p-3.5">Type</th>
                <th class="p-3.5">Amount</th>
                <th class="p-3.5">Reference / Notes</th>
                <th class="p-3.5">Status</th>
                <th class="p-3.5 text-right">Date & Time</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-800/60 font-sans">
              {% if transactions %}
                {% for tx in transactions %}
                <tr class="hover:bg-slate-900/40 transition">
                  <td class="p-3.5">
                    {% if tx.type == 'DEPOSIT' %}
                      <span class="px-2 py-0.5 rounded text-[10px] bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-semibold">UPI Deposit</span>
                    {% elif tx.type == 'BONUS' %}
                      <span class="px-2 py-0.5 rounded text-[10px] bg-pink-500/10 text-pink-400 border border-pink-500/20 font-semibold">Bonus</span>
                    {% elif tx.type == 'REFUND' %}
                      <span class="px-2 py-0.5 rounded text-[10px] bg-blue-500/10 text-blue-400 border border-blue-500/20 font-semibold">Refund</span>
                    {% elif tx.type == 'MANUAL_CREDIT' %}
                      <span class="px-2 py-0.5 rounded text-[10px] bg-purple-500/10 text-purple-400 border border-purple-500/20 font-semibold">Admin Credit</span>
                    {% else %}
                      <span class="px-2 py-0.5 rounded text-[10px] bg-slate-800 text-slate-400 border border-slate-700">Review Fee</span>
                    {% endif %}
                  </td>
                  <td class="p-3.5 font-mono font-bold {% if tx.type in ('DEPOSIT', 'BONUS', 'REFUND', 'MANUAL_CREDIT') %}text-emerald-400{% else %}text-slate-300{% endif %}">
                    {% if tx.type in ('DEPOSIT', 'BONUS', 'REFUND', 'MANUAL_CREDIT') %}+{% else %}-{% endif %}₹{{ "%.2f"|format(tx.amount) }}
                  </td>
                  <td class="p-3.5 text-slate-300">
                    {{ tx.notes or '-' }}
                    {% if tx.utr_ref %}<span class="block text-[10px] text-slate-500 font-mono">UTR: {{ tx.utr_ref }}</span>{% endif %}
                  </td>
                  <td class="p-3.5">
                    {% if tx.status == 'COMPLETED' %}
                      <span class="text-emerald-400 font-medium"><i class="fa-solid fa-check mr-1"></i>Completed</span>
                    {% elif tx.status == 'PENDING' %}
                      <span class="text-amber-400 font-medium"><i class="fa-solid fa-clock mr-1"></i>Verifying</span>
                    {% else %}
                      <span class="text-red-400 font-medium"><i class="fa-solid fa-xmark mr-1"></i>Rejected</span>
                    {% endif %}
                  </td>
                  <td class="p-3.5 text-right text-slate-400 font-mono text-[11px]">{{ tx.created_at[:16].replace('T', ' ') }}</td>
                </tr>
                {% endfor %}
              {% else %}
                <tr>
                  <td colspan="5" class="p-6 text-center text-slate-500">No transactions recorded yet.</td>
                </tr>
              {% endif %}
            </tbody>
          </table>
        </div>
      </div>

    </main>

    <script>
      const MIN_TOPUP = parseFloat("{{ settings.min_topup_amount }}") || 50;

      function switchTopupMethod(method) {
        console.log("Switching topup method to:", method);
        const autoSec = document.getElementById('section-auto-topup');
        const manualSec = document.getElementById('section-manual-topup');
        const tabAuto = document.getElementById('tab-auto');
        const tabManual = document.getElementById('tab-manual');

        if (method === 'manual') {
          if (autoSec) autoSec.classList.add('hidden');
          if (manualSec) manualSec.classList.remove('hidden');
          if (tabAuto) tabAuto.className = 'px-3.5 py-1.5 rounded-lg font-medium transition text-slate-400 hover:text-white cursor-pointer';
          if (tabManual) tabManual.className = 'px-3.5 py-1.5 rounded-lg font-semibold transition bg-amber-600 text-white shadow cursor-pointer';
        } else {
          if (manualSec) manualSec.classList.add('hidden');
          if (autoSec) autoSec.classList.remove('hidden');
          if (tabAuto) tabAuto.className = 'px-3.5 py-1.5 rounded-lg font-semibold transition bg-pink-600 text-white shadow cursor-pointer';
          if (tabManual) tabManual.className = 'px-3.5 py-1.5 rounded-lg font-medium transition text-slate-400 hover:text-white cursor-pointer';
        }
      }

      function setAutoAmount(val) {
        const el = document.getElementById('auto-deposit-amount');
        if (el) el.value = val;
      }

      function copyUPI() {
        const el = document.getElementById('upi-id-text');
        const text = el ? el.innerText.trim() : '';
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).then(() => {
            alert("UPI ID copied: " + text);
          }).catch(() => {
            prompt("Copy UPI ID:", text);
          });
        } else {
          prompt("Copy UPI ID:", text);
        }
      }

      async function payWithFamGateway() {
        console.log("payWithFamGateway triggered");
        const amountInput = document.getElementById('auto-deposit-amount');
        const amount = parseFloat(amountInput ? amountInput.value : 0);
        if (isNaN(amount) || amount < MIN_TOPUP) {
          alert("Minimum top-up amount is ₹" + MIN_TOPUP);
          return;
        }
        const btn = document.getElementById('btn-famgateway');
        if (btn) {
          btn.disabled = true;
          btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Initializing Checkout...';
        }

        try {
          const res = await fetch('/api/famgateway/initiate', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ amount: amount })
          });
          const d = await res.json();
          if (d.success && d.checkout_url) {
            window.location.href = d.checkout_url;
          } else {
            alert((d.error || "Failed to initialize payment gateway.") + " Please use Manual UPI Transfer if gateway is unavailable.");
            if (btn) {
              btn.disabled = false;
              btn.innerHTML = '<i class="fa-solid fa-bolt"></i> Proceed to Instant UPI Checkout';
            }
          }
        } catch (err) {
          alert("Error: " + err.message + ". Please use Manual UPI Transfer if gateway is unavailable.");
          if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<i class="fa-solid fa-bolt"></i> Proceed to Instant UPI Checkout';
          }
        }
      }

      async function handleManualTopupSubmit(e) {
        if (e) e.preventDefault();
        console.log("handleManualTopupSubmit triggered");
        const amountInput = document.getElementById('manual-deposit-amount');
        const amount = parseFloat(amountInput ? amountInput.value : 0);
        const utrInput = document.getElementById('manual-deposit-utr');
        const utr = utrInput ? utrInput.value.trim() : '';

        if (isNaN(amount) || amount < MIN_TOPUP) {
          alert("Minimum top-up amount is ₹" + MIN_TOPUP);
          return;
        }
        if (!utr || utr.length < 6) {
          alert("Please enter a valid 12-digit UPI UTR reference number.");
          return;
        }

        const btn = document.getElementById('btn-manual-deposit');
        if (btn) {
          btn.disabled = true;
          btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Submitting...';
        }

        try {
          const res = await fetch('/api/deposit', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ amount: amount, utr: utr })
          });
          const data = await res.json();
          if (data.success) {
            alert("Payment request submitted! Admin will verify and credit your wallet shortly.");
            location.reload();
          } else {
            alert(data.error || "Deposit submission failed.");
            if (btn) {
              btn.disabled = false;
              btn.innerHTML = '<i class="fa-solid fa-receipt"></i> Submit UTR for Verification';
            }
          }
        } catch (err) {
          alert("Error: " + err.message);
          if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<i class="fa-solid fa-receipt"></i> Submit UTR for Verification';
          }
        }
      }

      window.switchTopupMethod = switchTopupMethod;
      window.setAutoAmount = setAutoAmount;
      window.copyUPI = copyUPI;
      window.payWithFamGateway = payWithFamGateway;
      window.handleManualTopupSubmit = handleManualTopupSubmit;

      document.addEventListener('DOMContentLoaded', () => {
        const tabAuto = document.getElementById('tab-auto');
        const tabManual = document.getElementById('tab-manual');
        const btnFam = document.getElementById('btn-famgateway');
        const manualForm = document.getElementById('manual-topup-form');

        if (tabAuto) tabAuto.addEventListener('click', () => switchTopupMethod('auto'));
        if (tabManual) tabManual.addEventListener('click', () => switchTopupMethod('manual'));
        if (btnFam) btnFam.addEventListener('click', payWithFamGateway);
        if (manualForm) manualForm.addEventListener('submit', handleManualTopupSubmit);
      });
    </script>
</body>
</html>
"""

ADMIN_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Admin Studio Management - Meesho Automation</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
    body { font-family: 'Inter', sans-serif; }
    .font-mono { font-family: 'JetBrains Mono', monospace; }
  </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen flex flex-col">
  """ + BASE_NAV + """

  <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 flex-1 w-full space-y-8">

    <div class="flex items-center justify-between border-b border-slate-800 pb-4">
      <div>
        <h2 class="text-xl font-bold text-white flex items-center gap-2">
          <i class="fa-solid fa-shield-halved text-amber-400"></i>
          Administrator Control Panel
        </h2>
        <p class="text-xs text-slate-400">Manage Pricing, FamGateway Keys, Indian Proxies, Payment Verifications & Manual Wallet Top-ups.</p>
      </div>
      <a href="/" class="text-xs bg-slate-800 hover:bg-slate-700 text-slate-200 px-3.5 py-2 rounded-xl border border-slate-700 transition">
        <i class="fa-solid fa-arrow-left mr-1"></i> Back to Dashboard
      </a>
    </div>

    <!-- Admin Top Grid: Pending UPI Approvals & System Settings -->
    <div class="grid grid-cols-1 lg:grid-cols-12 gap-8">

      <!-- Left: Pending UPI Deposits (7 cols) -->
      <div class="lg:col-span-7 bg-slate-900/80 border border-slate-800 rounded-3xl p-6 shadow-xl space-y-4">
        <div class="flex items-center justify-between border-b border-slate-800 pb-3">
          <h3 class="text-sm font-bold text-white flex items-center gap-2">
            <i class="fa-solid fa-money-bill-transfer text-emerald-400"></i>
            Pending Manual UPI Payment Approvals
          </h3>
          <span class="text-xs font-mono bg-emerald-500/10 text-emerald-400 px-2 py-0.5 rounded-full border border-emerald-500/20">
            {{ pending_deposits|length }} pending
          </span>
        </div>

        <div class="overflow-x-auto">
          <table class="w-full text-left text-xs border-collapse">
            <thead>
              <tr class="border-b border-slate-800 text-slate-400 bg-slate-950/40">
                <th class="p-3">User</th>
                <th class="p-3">Amount</th>
                <th class="p-3">UTR Reference</th>
                <th class="p-3 text-right">Action</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-800/60 font-sans">
              {% if pending_deposits %}
                {% for d in pending_deposits %}
                <tr class="hover:bg-slate-900/40 transition">
                  <td class="p-3 font-semibold text-white">{{ d.username }}</td>
                  <td class="p-3 font-mono font-bold text-emerald-400">₹{{ "%.2f"|format(d.amount) }}</td>
                  <td class="p-3 font-mono text-slate-300">{{ d.utr_ref }}</td>
                  <td class="p-3 text-right space-x-1.5">
                    <button onclick="approveDeposit({{ d.id }})" class="bg-emerald-600 hover:bg-emerald-500 text-white text-[11px] px-2.5 py-1 rounded-lg transition font-medium">
                      Approve
                    </button>
                    <button onclick="rejectDeposit({{ d.id }})" class="bg-red-900/40 hover:bg-red-800 text-red-300 text-[11px] px-2.5 py-1 rounded-lg transition font-medium border border-red-700/50">
                      Reject
                    </button>
                  </td>
                </tr>
                {% endfor %}
              {% else %}
                <tr>
                  <td colspan="4" class="p-6 text-center text-slate-500">No pending UPI payments to review.</td>
                </tr>
              {% endif %}
            </tbody>
          </table>
        </div>
      </div>

      <!-- Right: Pricing & Integrations (5 cols) -->
      <div class="lg:col-span-5 bg-slate-900/80 border border-slate-800 rounded-3xl p-6 shadow-xl space-y-4">
        <h3 class="text-sm font-bold text-white flex items-center gap-2 border-b border-slate-800 pb-3">
          <i class="fa-solid fa-gear text-pink-500"></i>
          Service Pricing & Cloud Settings
        </h3>

        <form onsubmit="handleSaveSettings(event)" class="space-y-3.5">
          <div class="grid grid-cols-2 gap-3">
            <div>
              <label class="block text-[11px] text-slate-400 mb-1">Old Accounts (₹):</label>
              <input type="number" step="0.5" id="set-price-auto" value="{{ settings.price_auto_pilot }}" class="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-1.5 text-xs font-mono text-white focus:outline-none focus:border-pink-500">
            </div>
            <div>
              <label class="block text-[11px] text-slate-400 mb-1">Fresh Accounts (₹):</label>
              <input type="number" step="0.5" id="set-price-standard" value="{{ settings.price_standard_review }}" class="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-1.5 text-xs font-mono text-white focus:outline-none focus:border-pink-500">
            </div>
          </div>

          <div class="grid grid-cols-2 gap-3">
            <div>
              <label class="block text-[11px] text-slate-400 mb-1">Min Top-up Amount (₹):</label>
              <input type="number" step="1" id="set-min-topup" value="{{ settings.min_topup_amount }}" class="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-1.5 text-xs font-mono text-white focus:outline-none focus:border-pink-500">
            </div>
            <div>
              <label class="block text-[11px] text-slate-400 mb-1">Signup Bonus (₹):</label>
              <input type="number" step="1" id="set-signup-bonus" value="{{ settings.signup_bonus }}" class="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-1.5 text-xs font-mono text-white focus:outline-none focus:border-pink-500">
            </div>
          </div>

          <div>
            <label class="block text-[11px] text-slate-400 mb-1">FamGateway API Key (for UPI Gateway):</label>
            <input type="text" id="set-famgateway-key" value="{{ settings.famgateway_api_key }}" placeholder="Enter FamGateway API Key" class="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-1.5 text-xs font-mono text-pink-400 focus:outline-none focus:border-pink-500">
          </div>

          <div>
            <label class="block text-[11px] text-slate-400 mb-1">Indian Proxy for Meesho (e.g. http://ip:port or auto):</label>
            <input type="text" id="set-meesho-proxy" value="{{ settings.meesho_proxy }}" placeholder="e.g. http://103.x.x.x:80 or leave auto" class="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-1.5 text-xs font-mono text-slate-200 focus:outline-none focus:border-pink-500">
          </div>

          <div>
            <label class="block text-[11px] text-slate-400 mb-1">Fallback UPI ID:</label>
            <input type="text" id="set-upi-id" value="{{ settings.upi_id }}" class="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-1.5 text-xs font-mono text-slate-200 focus:outline-none focus:border-pink-500">
          </div>

          <!-- Telegram Bot Integration Toggle -->
          <div class="p-3 bg-slate-950/70 border border-slate-800 rounded-xl flex items-center justify-between">
            <div>
              <p class="text-xs font-semibold text-white">Telegram Auto-Refresh Integration</p>
              <p class="text-[10px] text-slate-400">Controls automated token refresh via @Meeshojsoncheckerbot</p>
            </div>
            <label class="relative inline-flex items-center cursor-pointer">
              <input type="checkbox" id="set-tg-enabled" {% if settings.telegram_bot_enabled == 'true' %}checked{% endif %} class="sr-only peer">
              <div class="w-9 h-5 bg-slate-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-pink-600"></div>
            </label>
          </div>

          <button type="submit" class="w-full bg-pink-600 hover:bg-pink-500 text-white text-xs font-medium py-2 rounded-xl transition">
            Save System Settings
          </button>
        </form>
      </div>

    </div>

    <!-- Users Management & Manual Wallet Top-up Table -->
    <div class="bg-slate-900/80 border border-slate-800 rounded-3xl p-6 shadow-xl space-y-4">
      <div class="flex items-center justify-between border-b border-slate-800 pb-3">
        <h3 class="text-sm font-bold text-white flex items-center gap-2">
          <i class="fa-solid fa-users text-blue-400"></i>
          User Accounts & Manual Wallet Credit
        </h3>
        <span class="text-xs text-slate-400 font-mono">{{ users|length }} Total Registered Users</span>
      </div>

      <div class="overflow-x-auto">
        <table class="w-full text-left text-xs border-collapse">
          <thead>
            <tr class="border-b border-slate-800 text-slate-400 bg-slate-950/40">
              <th class="p-3.5">User</th>
              <th class="p-3.5">Role</th>
              <th class="p-3.5">Balance</th>
              <th class="p-3.5">Tasks Total</th>
              <th class="p-3.5">Completed</th>
              <th class="p-3.5 text-right">Manual Wallet Adjust</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-800/60 font-sans">
            {% for u in users %}
            <tr class="hover:bg-slate-900/40 transition">
              <td class="p-3.5 font-semibold text-white">
                {{ u.username }}
                <span class="text-[10px] text-slate-500 block">{{ u.email or 'No email' }}</span>
              </td>
              <td class="p-3.5">
                {% if u.role == 'admin' %}
                  <span class="px-2 py-0.5 rounded text-[10px] bg-amber-500/10 text-amber-400 font-semibold border border-amber-500/20">Admin</span>
                {% else %}
                  <span class="px-2 py-0.5 rounded text-[10px] bg-slate-800 text-slate-400">User</span>
                {% endif %}
              </td>
              <td class="p-3.5 font-mono font-bold text-emerald-400">₹{{ "%.2f"|format(u.wallet_balance) }}</td>
              <td class="p-3.5 font-mono text-slate-300">{{ u.total_tasks }}</td>
              <td class="p-3.5 font-mono text-emerald-400">{{ u.completed_tasks }}</td>
              <td class="p-3.5 text-right">
                <button onclick="promptManualCredit({{ u.id }}, '{{ u.username }}')" class="bg-slate-800 hover:bg-slate-700 text-emerald-300 text-[11px] px-3 py-1 rounded-lg border border-slate-700 transition">
                  <i class="fa-solid fa-plus-minus mr-1"></i> Credit / Debit
                </button>
              </td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </div>

  </main>

  <script>
    async function handleSaveSettings(e) {
      e.preventDefault();
      const payload = {
        price_auto_pilot: document.getElementById('set-price-auto').value,
        price_standard_review: document.getElementById('set-price-standard').value,
        min_topup_amount: document.getElementById('set-min-topup').value,
        signup_bonus: document.getElementById('set-signup-bonus').value,
        famgateway_api_key: document.getElementById('set-famgateway-key').value,
        meesho_proxy: document.getElementById('set-meesho-proxy').value,
        upi_id: document.getElementById('set-upi-id').value,
        telegram_bot_enabled: document.getElementById('set-tg-enabled').checked ? 'true' : 'false'
      };

      try {
        const res = await fetch('/api/admin/settings', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(payload)
        });
        const d = await res.json();
        if (d.success) alert("Settings successfully updated!");
      } catch (err) {
        alert("Failed to save settings: " + err.message);
      }
    }

    async function approveDeposit(txId) {
      if (!confirm("Approve this payment and credit user wallet?")) return;
      const res = await fetch(`/api/admin/deposit/${txId}/approve`, {method: 'POST'});
      const d = await res.json();
      if (d.success) location.reload();
      else alert(d.error || "Approval failed");
    }

    async function rejectDeposit(txId) {
      if (!confirm("Reject this payment request?")) return;
      const res = await fetch(`/api/admin/deposit/${txId}/reject`, {method: 'POST'});
      const d = await res.json();
      if (d.success) location.reload();
      else alert(d.error || "Rejection failed");
    }

    async function promptManualCredit(userId, username) {
      const amountStr = prompt(`Enter amount to Credit (+) or Debit (-) for ${username} (e.g. 100 or -50):`);
      if (!amountStr) return;
      const amount = parseFloat(amountStr);
      if (isNaN(amount) || amount === 0) {
        alert("Invalid amount.");
        return;
      }
      const note = prompt("Enter note / reason for this adjustment (optional):", "Admin manual adjustment");

      try {
        const res = await fetch('/api/admin/wallet_adjust', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ user_id: userId, amount: amount, note: note || 'Admin adjustment' })
        });
        const d = await res.json();
        if (d.success) {
          alert(`Successfully updated wallet balance for ${username}!`);
          location.reload();
        } else {
          alert(d.error || "Failed to adjust balance");
        }
      } catch (e) {
        alert("Error: " + e.message);
      }
    }
  </script>
</body>
</html>
"""

LOGIN_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Sign In - Meesho Automation Studio</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen flex items-center justify-center p-4">
  <div class="max-w-md w-full bg-slate-900 border border-slate-800 rounded-3xl p-8 shadow-2xl space-y-6">
    <div class="text-center space-y-2">
      <div class="h-12 w-12 rounded-2xl bg-gradient-to-tr from-fuchsia-600 to-pink-500 flex items-center justify-center shadow-lg shadow-pink-500/20 mx-auto">
        <i class="fa-solid fa-star text-white text-xl"></i>
      </div>
      <h2 class="text-xl font-bold text-white tracking-tight">Sign In to Your Account</h2>
      <p class="text-xs text-slate-400">Enter your credentials to access your dashboard</p>
    </div>

    {% with messages = get_flashed_messages(with_categories=true) %}
      {% if messages %}
        {% for category, message in messages %}
          <div class="p-3 rounded-xl text-xs {% if category == 'error' %}bg-red-500/10 text-red-400 border border-red-500/20{% else %}bg-emerald-500/10 text-emerald-400 border border-emerald-500/20{% endif %}">
            {{ message }}
          </div>
        {% endfor %}
      {% endif %}
    {% endwith %}

    <form method="POST" action="/login" class="space-y-4">
      <div>
        <label class="block text-xs font-semibold text-slate-300 mb-1">Username:</label>
        <input type="text" name="username" required placeholder="Enter username" class="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-xs text-white focus:outline-none focus:border-pink-500">
      </div>

      <div>
        <label class="block text-xs font-semibold text-slate-300 mb-1">Password:</label>
        <input type="password" name="password" required placeholder="••••••••" class="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-xs text-white focus:outline-none focus:border-pink-500">
      </div>

      <button type="submit" class="w-full bg-gradient-to-r from-pink-600 to-fuchsia-600 hover:from-pink-500 hover:to-fuchsia-500 text-white font-medium text-xs py-3 rounded-xl shadow-lg shadow-pink-600/20 transition">
        Sign In
      </button>
    </form>

    <div class="pt-2 border-t border-slate-800 text-center text-xs text-slate-400">
      Don't have an account? <a href="/register" class="text-pink-400 hover:underline font-medium">Create New Account</a>
    </div>
  </div>
</body>
</html>
"""

REGISTER_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Register - Meesho Automation Studio</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen flex items-center justify-center p-4">
  <div class="max-w-md w-full bg-slate-900 border border-slate-800 rounded-3xl p-8 shadow-2xl space-y-6">
    <div class="text-center space-y-2">
      <div class="h-12 w-12 rounded-2xl bg-gradient-to-tr from-fuchsia-600 to-pink-500 flex items-center justify-center shadow-lg shadow-pink-500/20 mx-auto">
        <i class="fa-solid fa-user-plus text-white text-xl"></i>
      </div>
      <h2 class="text-xl font-bold text-white tracking-tight">Create Client Account</h2>
      <p class="text-xs text-slate-400">Sign up to start automated order reviews</p>
    </div>

    {% with messages = get_flashed_messages(with_categories=true) %}
      {% if messages %}
        {% for category, message in messages %}
          <div class="p-3 rounded-xl text-xs {% if category == 'error' %}bg-red-500/10 text-red-400 border border-red-500/20{% else %}bg-emerald-500/10 text-emerald-400 border border-emerald-500/20{% endif %}">
            {{ message }}
          </div>
        {% endfor %}
      {% endif %}
    {% endwith %}

    <form method="POST" action="/register" class="space-y-4">
      <div>
        <label class="block text-xs font-semibold text-slate-300 mb-1">Choose Username:</label>
        <input type="text" name="username" required placeholder="Choose a username" class="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-xs text-white focus:outline-none focus:border-pink-500">
      </div>

      <div>
        <label class="block text-xs font-semibold text-slate-300 mb-1">Email Address (Optional):</label>
        <input type="email" name="email" placeholder="email@example.com" class="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-xs text-white focus:outline-none focus:border-pink-500">
      </div>

      <div>
        <label class="block text-xs font-semibold text-slate-300 mb-1">Password:</label>
        <input type="password" name="password" required minlength="6" placeholder="••••••••" class="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-xs text-white focus:outline-none focus:border-pink-500">
      </div>

      <button type="submit" class="w-full bg-gradient-to-r from-pink-600 to-fuchsia-600 hover:from-pink-500 hover:to-fuchsia-500 text-white font-medium text-xs py-3 rounded-xl shadow-lg shadow-pink-600/20 transition">
        Create Account
      </button>
    </form>

    <div class="pt-2 border-t border-slate-800 text-center text-xs text-slate-400">
      Already have an account? <a href="/login" class="text-pink-400 hover:underline font-medium">Sign In</a>
    </div>
  </div>
</body>
</html>
"""


# ------------------------------------------------------------
# Web Routes
# ------------------------------------------------------------
@app.route("/")
@login_required
def dashboard_page():
    user = db.get_user_by_id(session["user_id"])
    tasks = db.get_user_tasks(user["id"])
    stats = db.get_user_stats(user["id"])
    prices = {
        "price_auto_pilot": db.get_setting("price_auto_pilot", "10.0"),
        "price_standard_review": db.get_setting("price_standard_review", "7.0"),
    }
    return render_template_string(
        DASHBOARD_HTML,
        user=user,
        tasks=tasks,
        stats=stats,
        prices=prices,
        session=session,
    )


@app.route("/wallet")
@login_required
def wallet_page():
    user = db.get_user_by_id(session["user_id"])

    # Auto-verify any pending FamGateway orders for this user upon loading wallet page
    api_key = db.get_setting("famgateway_api_key")
    if api_key:
        target_order_id = request.args.get("order_id")
        user_txs = db.get_user_transactions(user["id"])
        pending_gw_orders = [t["gateway_order_id"] for t in user_txs if t["status"] == "PENDING" and t.get("gateway_order_id")]
        if target_order_id and target_order_id not in pending_gw_orders:
            pending_gw_orders.append(target_order_id)

        for g_id in pending_gw_orders:
            try:
                ok, v_data = famgateway_client.verify_order(g_id, api_key)
                if ok:
                    credited = db.complete_gateway_deposit(g_id)
                    if credited:
                        flash("Payment confirmed! Your wallet balance has been updated.", "success")
                        user = db.get_user_by_id(session["user_id"])  # Refresh balance
            except Exception:
                pass

    transactions = db.get_user_transactions(user["id"])
    settings = db.get_all_settings()
    return render_template_string(
        WALLET_HTML,
        user=user,
        transactions=transactions,
        settings=settings,
        session=session,
    )


@app.route("/admin")
@admin_required
def admin_page():
    user = db.get_user_by_id(session["user_id"])
    users = db.get_all_users()
    pending_deposits = db.get_pending_deposits()
    settings = db.get_all_settings()
    return render_template_string(
        ADMIN_HTML,
        user=user,
        users=users,
        pending_deposits=pending_deposits,
        settings=settings,
        session=session,
    )


@app.route("/login", methods=["GET", "POST"])
def login_page():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        user = db.authenticate_user(username, password)
        if user:
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            return redirect(url_for("dashboard_page"))
        else:
            flash("Invalid username or password.", "error")
    return render_template_string(LOGIN_HTML)


@app.route("/register", methods=["GET", "POST"])
def register_page():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        email = request.form.get("email", "")
        user_id = db.create_user(username, password, email)
        if user_id:
            flash("Account registered successfully! Please log in.", "success")
            return redirect(url_for("login_page"))
        else:
            flash("Username already exists. Please choose another.", "error")
    return render_template_string(REGISTER_HTML)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login_page"))


# ------------------------------------------------------------
# API Endpoints
# ------------------------------------------------------------
@app.route("/api/sample", methods=["GET"])
def api_sample():
    samples = []
    for fn in ["meesho_account_8869049741.json", "7977748514.json"]:
        p = Path(fn)
        if p.is_file():
            try:
                samples.append(json.loads(p.read_text(encoding="utf-8")))
            except Exception:
                pass
    return jsonify(samples)


@app.route("/api/submit_jobs", methods=["POST"])
@login_required
def api_submit_jobs():
    data = request.json or {}
    raw_text = data.get("raw_text", "")
    service_type = data.get("service_type", "auto_pilot")
    rating_mode = str(data.get("rating_mode") or data.get("rating_stars") or "5")
    review_mode = str(data.get("review_mode", "auto"))
    comments = str(data.get("comments", "")).strip()

    accounts = parse_multi_jsons(raw_text)
    if not accounts:
        return jsonify({"success": False, "error": "No valid accounts with mandatory 'mobile' and 'xo' were parsed."})

    res = dispatch_batch_tasks(
        user_id=session["user_id"],
        accounts=accounts,
        service_type=service_type,
        rating_mode=rating_mode,
        review_mode=review_mode,
        custom_comments=comments,
    )
    return jsonify(res)


@app.route("/api/change_password", methods=["POST"])
@login_required
def api_change_password():
    data = request.json or {}
    current_pwd = str(data.get("current_password", ""))
    new_pwd = str(data.get("new_password", ""))

    if len(new_pwd) < 6:
        return jsonify({"success": False, "error": "New password must be at least 6 characters."})

    ok, msg = db.change_password(session["user_id"], current_pwd, new_pwd)
    return jsonify({"success": ok, "message": msg, "error": msg if not ok else None})


@app.route("/api/deposit", methods=["POST"])
@login_required
def api_deposit():
    """Manual UTR submission for wallet top-up."""
    data = request.json or {}
    amount = float(data.get("amount", 0))
    utr = str(data.get("utr", "")).strip()
    min_topup = float(db.get_setting("min_topup_amount", "50.0"))

    if amount < min_topup:
        return jsonify({"success": False, "error": f"Minimum top-up amount is ₹{min_topup:.2f}."})

    if not utr or len(utr) < 6:
        return jsonify({"success": False, "error": "Invalid UTR reference number."})

    tx_id = db.create_deposit_request(session["user_id"], amount, utr)
    return jsonify({"success": True, "tx_id": tx_id})


@app.route("/api/famgateway/initiate", methods=["POST"])
@login_required
def api_famgateway_initiate():
    """Initiates automated FamGateway UPI checkout session."""
    data = request.json or {}
    amount = float(data.get("amount", 0))
    min_topup = float(db.get_setting("min_topup_amount", "50.0"))

    if amount < min_topup:
        return jsonify({"success": False, "error": f"Minimum top-up amount is ₹{min_topup:.2f}."})

    api_key = (db.get_setting("famgateway_api_key") or os.environ.get("FAMGATEWAY_API_KEY") or "").strip()
    if not api_key:
        return jsonify({"success": False, "error": "FamGateway API key is not configured. Please use Manual UPI Transfer."})

    user = db.get_user_by_id(session["user_id"])
    redirect_url = request.host_url.rstrip("/") + url_for("wallet_page")
    webhook_url = request.host_url.rstrip("/") + "/api/webhook/famgateway"

    ok, resp = famgateway_client.create_order(
        amount=amount,
        customer_name=user["username"],
        redirect_url=redirect_url,
        webhook_url=webhook_url,
        api_key=api_key,
    )

    if ok:
        data_obj = resp.get("data") if isinstance(resp.get("data"), dict) else {}
        order_id = str(resp.get("order_id") or data_obj.get("order_id") or "")
        checkout_url = str(resp.get("checkout_url") or data_obj.get("checkout_url") or resp.get("payment_url") or "")

        if not checkout_url:
            return jsonify({"success": False, "error": "Gateway did not return checkout URL. Please use Manual UPI Transfer."})

        # Create pending transaction
        db.create_deposit_request(session["user_id"], amount, utr_ref="FamGateway", gateway_order_id=order_id)
        return jsonify({
            "success": True,
            "checkout_url": checkout_url,
            "order_id": order_id,
            "qr_url": str(resp.get("qr_url") or data_obj.get("qr_url") or ""),
            "upi_intent": str(resp.get("upi_intent") or data_obj.get("upi_intent") or "")
        })
    else:
        err_msg = resp.get("error") or resp.get("message") or "Failed to create gateway order. Please use Manual UPI Transfer."
        return jsonify({"success": False, "error": err_msg})


@app.route("/api/webhook/famgateway", methods=["POST"])
def api_famgateway_webhook():
    """Receives and verifies automated payment settlement notifications from FamGateway."""
    raw_body = request.get_data()
    sig_header = request.headers.get("X-FamGateway-Signature", "")
    api_key = db.get_setting("famgateway_api_key")

    # If signature header is provided, verify it
    if sig_header and api_key:
        if not famgateway_client.verify_webhook_signature(raw_body, sig_header, api_key):
            return jsonify({"status": "error", "message": "Invalid signature"}), 403

    try:
        payload = request.json or {}
        order_id = str(payload.get("order_id") or payload.get("orderId") or "")
        status = str(payload.get("status") or "").upper()

        if order_id and status in ("SUCCESS", "PAID", "COMPLETED"):
            db.complete_gateway_deposit(order_id)
            return jsonify({"status": "success", "message": "Wallet credited successfully."})
        return jsonify({"status": "ignored", "message": "Status not completed."})
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500


@app.route("/api/admin/deposit/<int:tx_id>/approve", methods=["POST"])
@admin_required
def api_admin_approve_deposit(tx_id):
    ok = db.approve_deposit(tx_id)
    return jsonify({"success": ok})


@app.route("/api/admin/deposit/<int:tx_id>/reject", methods=["POST"])
@admin_required
def api_admin_reject_deposit(tx_id):
    ok = db.reject_deposit(tx_id)
    return jsonify({"success": ok})


@app.route("/api/admin/settings", methods=["POST"])
@admin_required
def api_admin_save_settings():
    data = request.json or {}
    for k, v in data.items():
        db.set_setting(k, str(v))
    return jsonify({"success": True})


@app.route("/api/admin/wallet_adjust", methods=["POST"])
@admin_required
def api_admin_wallet_adjust():
    data = request.json or {}
    user_id = int(data.get("user_id"))
    amount = float(data.get("amount", 0))
    note = str(data.get("note", "Admin adjustment"))

    tx_type = "MANUAL_CREDIT" if amount >= 0 else "MANUAL_DEBIT"
    ok = db.update_user_balance(user_id, amount, tx_type, notes=note)
    return jsonify({"success": ok})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
