from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.request import urlopen

from app.control import ControlPlane
from app.runtime import RuntimeSnapshot, runtime_snapshot_to_dict

UI_VERSION = "2026-04-19-web-terminal-v5"
WEB_MAX_RECENT_ROWS = 18
WEB_MAX_PRICE_POINTS = 90
WEB_MAX_EQUITY_POINTS = 120
WEB_MAX_POSITIONS = 60
WEB_MAX_BALANCE_PREVIEW = 12
WEB_MAX_MARKET_ROWS = 180


HTML_PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Quant Desk 中文交易台</title>
  <style>
    :root {
      --bg: #f6f1e8;
      --bg-2: #e9dfcf;
      --paper: rgba(255, 251, 245, 0.9);
      --paper-strong: rgba(255, 255, 255, 0.94);
      --ink: #0f1b1a;
      --muted: #596461;
      --line: rgba(22, 37, 34, 0.10);
      --accent: #095b49;
      --accent-2: #d46a26;
      --accent-soft: rgba(9, 91, 73, 0.10);
      --accent-2-soft: rgba(212, 106, 38, 0.13);
      --danger: #a33026;
      --danger-soft: rgba(163, 48, 38, 0.10);
      --shadow: 0 30px 60px rgba(40, 29, 12, 0.12);
      --radius-xl: 28px;
      --radius-lg: 20px;
      --radius-md: 14px;
    }
    * { box-sizing: border-box; }
    html { scroll-behavior: smooth; }
    body {
      margin: 0;
      color: var(--ink);
      font-family: "SF Pro Display", "PingFang SC", "Avenir Next", sans-serif;
      background:
        radial-gradient(circle at top left, rgba(9,91,73,0.14), transparent 30%),
        radial-gradient(circle at 85% 0%, rgba(212,106,38,0.12), transparent 20%),
        linear-gradient(180deg, #fbf7f0 0%, var(--bg) 42%, var(--bg-2) 100%);
      min-height: 100vh;
    }
    .shell {
      max-width: 1520px;
      margin: 0 auto;
      padding: 28px 22px 40px;
    }
    .hero {
      display: grid;
      grid-template-columns: 1.3fr 0.9fr;
      gap: 18px;
      margin-bottom: 18px;
    }
    .cockpit-strip {
      display: grid;
      gap: 16px;
      margin-bottom: 18px;
    }
    .cockpit-grid {
      display: grid;
      grid-template-columns: 1.2fr repeat(3, minmax(0, 1fr));
      gap: 12px;
    }
    .status-card {
      border-radius: 20px;
      padding: 18px;
      border: 1px solid rgba(22,37,34,0.08);
      background: linear-gradient(180deg, rgba(255,255,255,0.94), rgba(249,244,236,0.88));
    }
    .status-card.dark {
      background:
        linear-gradient(135deg, rgba(15,27,26,0.96), rgba(19,57,49,0.96)),
        linear-gradient(140deg, rgba(9,91,73,0.24), rgba(212,106,38,0.18));
      color: #f8f3eb;
      border-color: rgba(248,243,235,0.08);
    }
    .status-card.dark .metric-label,
    .status-card.dark .metric-sub {
      color: rgba(248,243,235,0.70);
    }
    .status-big {
      font-size: 28px;
      font-weight: 900;
      line-height: 1;
      letter-spacing: 0.02em;
    }
    .status-inline {
      padding: 12px 14px;
      border-radius: 16px;
      border: 1px solid rgba(22,37,34,0.08);
      background: rgba(255,255,255,0.72);
      color: var(--muted);
      font-size: 13px;
      line-height: 1.65;
    }
    .progress-wrap {
      display: grid;
      gap: 8px;
    }
    .progress-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      font-size: 12px;
      color: var(--muted);
    }
    .progress-track {
      position: relative;
      width: 100%;
      height: 14px;
      border-radius: 999px;
      overflow: hidden;
      background: rgba(22,37,34,0.08);
      border: 1px solid rgba(22,37,34,0.08);
    }
    .progress-fill {
      position: absolute;
      inset: 0 auto 0 0;
      width: 6%;
      border-radius: 999px;
      background: linear-gradient(90deg, rgba(9,91,73,0.96), rgba(212,106,38,0.96));
      transition: width 240ms ease;
    }
    .sync-strip {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
    }
    .sync-chip {
      padding: 12px 14px;
      border-radius: 16px;
      border: 1px solid rgba(22,37,34,0.08);
      background: rgba(255,255,255,0.72);
      color: var(--muted);
      font-size: 12px;
      line-height: 1.55;
      min-height: 66px;
    }
    .sync-chip strong {
      display: block;
      color: var(--ink);
      font-size: 13px;
      margin-bottom: 6px;
    }
    .pulse-strip {
      display: flex;
      gap: 10px;
      overflow: auto;
      padding-bottom: 2px;
    }
    .pulse-chip {
      min-width: 170px;
      border-radius: 18px;
      border: 1px solid rgba(22,37,34,0.08);
      background: rgba(255,255,255,0.78);
      padding: 14px;
      cursor: pointer;
      transition: transform 140ms ease, border-color 140ms ease, background 140ms ease;
    }
    .pulse-chip:hover {
      transform: translateY(-1px);
      border-color: rgba(9,91,73,0.18);
      background: rgba(255,255,255,0.92);
    }
    .pulse-chip.active {
      border-color: rgba(9,91,73,0.24);
      background: linear-gradient(135deg, rgba(9,91,73,0.12), rgba(255,255,255,0.92));
    }
    .pulse-chip .symbol {
      font-size: 17px;
      font-weight: 900;
      line-height: 1.1;
    }
    .pulse-chip .meta {
      color: var(--muted);
      font-size: 12px;
      margin-top: 6px;
      line-height: 1.55;
    }
    .panel {
      background: var(--paper);
      border: 1px solid var(--line);
      box-shadow: var(--shadow);
      backdrop-filter: blur(14px);
      border-radius: var(--radius-xl);
      padding: 22px;
    }
    .headline {
      min-height: 210px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      background:
        linear-gradient(135deg, rgba(255,255,255,0.78), rgba(255,255,255,0.58)),
        linear-gradient(135deg, rgba(9,91,73,0.06), rgba(212,106,38,0.09));
    }
    .headline h1 {
      margin: 0;
      font-size: 42px;
      line-height: 0.95;
      letter-spacing: 0.03em;
      text-transform: uppercase;
    }
    .headline p {
      margin: 12px 0 0;
      max-width: 760px;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.6;
    }
    .hero-strip {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 18px;
    }
    .badge, .pill {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 9px 14px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 800;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      border: 1px solid transparent;
      white-space: nowrap;
    }
    .badge, .pill.ok {
      color: var(--accent);
      background: var(--accent-soft);
      border-color: rgba(9,91,73,0.18);
    }
    .pill.warn {
      color: var(--accent-2);
      background: var(--accent-2-soft);
      border-color: rgba(212,106,38,0.18);
    }
    .pill.danger {
      color: var(--danger);
      background: var(--danger-soft);
      border-color: rgba(163,48,38,0.18);
    }
    .hero-note {
      min-height: 210px;
      display: flex;
      flex-direction: column;
      gap: 14px;
      justify-content: space-between;
      background:
        linear-gradient(180deg, rgba(15,27,26,0.92), rgba(15,27,26,0.86)),
        linear-gradient(120deg, rgba(9,91,73,0.25), rgba(212,106,38,0.20));
      color: #f8f3eb;
    }
    .section-kicker {
      font-size: 11px;
      letter-spacing: 0.16em;
      text-transform: uppercase;
      color: rgba(248,243,235,0.68);
    }
    .hero-note .big-value {
      font-size: 36px;
      font-weight: 900;
      line-height: 1;
      letter-spacing: 0.04em;
    }
    .hero-note .subline {
      color: rgba(248,243,235,0.72);
      line-height: 1.55;
      font-size: 14px;
    }
    .layout {
      display: grid;
      grid-template-columns: 360px minmax(0, 1fr);
      gap: 18px;
    }
    .left-rail {
      display: grid;
      gap: 18px;
      align-content: start;
    }
    .main-rail {
      display: grid;
      gap: 18px;
    }
    .title-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 14px;
    }
    .title-row h2, .title-row h3 {
      margin: 0;
      font-size: 14px;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: var(--muted);
    }
    .muted {
      color: var(--muted);
      font-size: 12px;
    }
    .control-stack, .summary-stack {
      display: grid;
      gap: 12px;
    }
    .field label {
      display: block;
      margin-bottom: 8px;
      font-size: 11px;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: var(--muted);
    }
    .field select, .field input, .field button, .action-btn {
      width: 100%;
      border: 1px solid var(--line);
      background: var(--paper-strong);
      color: var(--ink);
      border-radius: var(--radius-md);
      padding: 12px 14px;
      font-size: 14px;
      outline: none;
      transition: transform 140ms ease, border-color 140ms ease, background 140ms ease;
    }
    .field select:focus, .field input:focus {
      border-color: rgba(9,91,73,0.28);
    }
    .action-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
    }
    .action-btn {
      cursor: pointer;
      font-weight: 700;
      background: linear-gradient(180deg, rgba(255,255,255,0.95), rgba(245,239,230,0.95));
    }
    .action-btn.primary {
      background: linear-gradient(135deg, rgba(9,91,73,0.96), rgba(15,111,88,0.96));
      color: #f6f1e8;
      border-color: rgba(9,91,73,0.24);
    }
    .action-btn.secondary {
      background: linear-gradient(135deg, rgba(212,106,38,0.96), rgba(233,128,62,0.96));
      color: #fff8f2;
      border-color: rgba(212,106,38,0.24);
    }
    .action-btn.ghost {
      background: rgba(255,255,255,0.84);
    }
    .action-btn:hover {
      transform: translateY(-1px);
    }
    .action-btn:disabled {
      cursor: not-allowed;
      opacity: 0.48;
      transform: none;
    }
    .inline-note {
      font-size: 12px;
      color: var(--muted);
      line-height: 1.6;
    }
    .event-list {
      display: grid;
      gap: 10px;
      max-height: 280px;
      overflow: auto;
      padding-right: 4px;
    }
    .event-item {
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 12px 13px;
      background: rgba(255,255,255,0.72);
    }
    .event-item strong {
      display: block;
      margin-bottom: 4px;
      font-size: 13px;
    }
    .event-item span {
      display: block;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.5;
    }
    .summary-card {
      display: grid;
      gap: 10px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
    .micro-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }
    .metric-card {
      border-radius: 18px;
      padding: 16px;
      background: linear-gradient(180deg, rgba(255,255,255,0.94), rgba(249,244,236,0.86));
      border: 1px solid var(--line);
    }
    .metric-label {
      font-size: 11px;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: var(--muted);
      margin-bottom: 10px;
    }
    .metric-value {
      font-size: 30px;
      font-weight: 900;
      line-height: 1;
    }
    .metric-sub {
      margin-top: 8px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.5;
    }
    .filter-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
    }
    .plan-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }
    .plan-card {
      border: 1px solid var(--line);
      border-radius: 22px;
      background:
        linear-gradient(180deg, rgba(255,255,255,0.95), rgba(249,244,236,0.88));
      padding: 18px;
      display: grid;
      gap: 12px;
      min-height: 220px;
    }
    .plan-top {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 14px;
    }
    .plan-title {
      font-size: 28px;
      font-weight: 900;
      line-height: 0.95;
      letter-spacing: 0.02em;
    }
    .plan-sub {
      color: var(--muted);
      font-size: 13px;
      margin-top: 7px;
    }
    .plan-body {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }
    .plan-stat {
      padding: 12px;
      border-radius: 16px;
      background: rgba(245, 240, 232, 0.84);
      border: 1px solid rgba(22,37,34,0.08);
    }
    .plan-stat-label {
      font-size: 11px;
      color: var(--muted);
      letter-spacing: 0.10em;
      text-transform: uppercase;
      margin-bottom: 7px;
    }
    .plan-stat-value {
      font-size: 18px;
      font-weight: 800;
      line-height: 1.2;
    }
    .plan-reason {
      color: var(--muted);
      font-size: 13px;
      line-height: 1.6;
      min-height: 46px;
    }
    .analysis-layout {
      display: grid;
      grid-template-columns: 1.25fr 0.95fr;
      gap: 14px;
    }
    .analysis-card {
      border-radius: 24px;
      border: 1px solid var(--line);
      background:
        linear-gradient(135deg, rgba(15,27,26,0.96), rgba(19,57,49,0.96)),
        linear-gradient(140deg, rgba(9,91,73,0.24), rgba(212,106,38,0.18));
      color: #f8f3eb;
      padding: 22px;
      display: grid;
      gap: 14px;
      min-height: 260px;
    }
    .analysis-card .section-kicker {
      color: rgba(248,243,235,0.62);
    }
    .analysis-title {
      font-size: 38px;
      font-weight: 900;
      line-height: 0.94;
      letter-spacing: 0.02em;
    }
    .analysis-reason {
      color: rgba(248,243,235,0.76);
      font-size: 14px;
      line-height: 1.7;
    }
    .analysis-stats {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }
    .analysis-stat {
      padding: 12px;
      border-radius: 16px;
      border: 1px solid rgba(248,243,235,0.10);
      background: rgba(248,243,235,0.08);
    }
    .analysis-stat .plan-stat-label {
      color: rgba(248,243,235,0.62);
    }
    .analysis-stat .plan-stat-value {
      color: #fff7ed;
    }
    .analysis-advice {
      padding: 14px 16px;
      border-radius: 18px;
      background: rgba(248,243,235,0.08);
      border: 1px solid rgba(248,243,235,0.12);
      color: rgba(248,243,235,0.92);
      line-height: 1.7;
      font-size: 14px;
    }
    .market-board-card {
      display: grid;
      gap: 10px;
    }
    .market-board-toolbar {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 180px auto;
      gap: 10px;
      align-items: end;
    }
    .board-stats {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }
    .board-stat {
      border-radius: 16px;
      padding: 12px;
      border: 1px solid rgba(22,37,34,0.08);
      background: rgba(255,255,255,0.72);
    }
    .market-board-scroll {
      max-height: 360px;
      overflow: auto;
      padding-right: 4px;
    }
    .market-row {
      display: grid;
      grid-template-columns: 1.2fr 0.9fr 0.9fr 0.7fr;
      gap: 12px;
      align-items: center;
      padding: 13px 12px;
      border-radius: 18px;
      border: 1px solid rgba(22,37,34,0.08);
      background: rgba(255,255,255,0.78);
      margin-bottom: 8px;
      cursor: pointer;
      transition: transform 140ms ease, border-color 140ms ease, background 140ms ease;
    }
    .market-row:hover {
      transform: translateY(-1px);
      border-color: rgba(9,91,73,0.18);
      background: rgba(255,255,255,0.92);
    }
    .market-row.active {
      border-color: rgba(9,91,73,0.26);
      background: linear-gradient(135deg, rgba(9,91,73,0.10), rgba(255,255,255,0.92));
      box-shadow: inset 0 0 0 1px rgba(9,91,73,0.08);
    }
    .market-symbol {
      font-size: 18px;
      font-weight: 900;
      line-height: 1.1;
    }
    .market-sub {
      color: var(--muted);
      font-size: 12px;
      margin-top: 4px;
    }
    .positive {
      color: var(--accent);
    }
    .negative {
      color: var(--danger);
    }
    .manual-stack {
      display: grid;
      gap: 10px;
    }
    .manual-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }
    .manual-note {
      padding: 10px 12px;
      border-radius: 14px;
      background: rgba(9,91,73,0.08);
      border: 1px solid rgba(9,91,73,0.10);
      color: var(--muted);
      font-size: 12px;
      line-height: 1.6;
    }
    .network-card {
      display: grid;
      gap: 12px;
    }
    .network-summary {
      padding: 12px 14px;
      border-radius: 16px;
      background: rgba(15,27,26,0.92);
      color: #f8f3eb;
      line-height: 1.6;
      font-size: 13px;
    }
    .network-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }
    .network-item {
      border-radius: 16px;
      padding: 12px;
      background: rgba(255,255,255,0.72);
      border: 1px solid rgba(22,37,34,0.08);
    }
    .stack-list {
      display: grid;
      gap: 8px;
    }
    .stack-row {
      padding: 10px 12px;
      border-radius: 14px;
      background: rgba(255,255,255,0.72);
      border: 1px solid rgba(22,37,34,0.08);
      font-size: 13px;
      line-height: 1.55;
    }
    .snippet-box {
      padding: 12px;
      border-radius: 16px;
      background: rgba(15,27,26,0.94);
      color: #f8f3eb;
      border: 1px solid rgba(248,243,235,0.08);
      font-family: "JetBrains Mono", "SFMono-Regular", monospace;
      font-size: 12px;
      line-height: 1.6;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .table-action-btn {
      border: 1px solid rgba(212,106,38,0.18);
      background: rgba(212,106,38,0.10);
      color: var(--accent-2);
      border-radius: 999px;
      padding: 7px 10px;
      cursor: pointer;
      font-size: 12px;
      font-weight: 700;
      white-space: nowrap;
    }
    .table-action-btn:disabled {
      opacity: 0.45;
      cursor: not-allowed;
    }
    .chart-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 14px;
    }
    .chart-card, .table-card {
      border-radius: var(--radius-lg);
      border: 1px solid var(--line);
      background: var(--paper);
      box-shadow: var(--shadow);
      padding: 18px;
    }
    .chart {
      width: 100%;
      min-height: 220px;
      border-radius: 18px;
      background:
        linear-gradient(180deg, rgba(255,255,255,0.40), rgba(255,255,255,0.72)),
        repeating-linear-gradient(
          to bottom,
          rgba(89,100,97,0.07) 0,
          rgba(89,100,97,0.07) 1px,
          transparent 1px,
          transparent 40px
        );
      border: 1px solid rgba(22,37,34,0.08);
      display: flex;
      align-items: center;
      justify-content: center;
      overflow: hidden;
    }
    .chart svg {
      width: 100%;
      height: 220px;
      display: block;
    }
    .chart-empty {
      padding: 24px;
      color: var(--muted);
      font-size: 14px;
      text-align: center;
    }
    .tables-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }
    .full-width {
      grid-column: 1 / -1;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }
    th, td {
      padding: 10px 8px;
      border-bottom: 1px solid rgba(22,37,34,0.08);
      text-align: left;
      vertical-align: top;
    }
    th {
      color: var(--muted);
      font-size: 11px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }
    .mono { font-family: "JetBrains Mono", "SFMono-Regular", monospace; }
    .toast {
      position: fixed;
      right: 18px;
      bottom: 18px;
      min-width: 240px;
      max-width: 360px;
      padding: 14px 16px;
      border-radius: 16px;
      background: rgba(15,27,26,0.92);
      color: #f8f3eb;
      box-shadow: var(--shadow);
      font-size: 13px;
      line-height: 1.5;
      opacity: 0;
      transform: translateY(12px);
      pointer-events: none;
      transition: opacity 160ms ease, transform 160ms ease;
    }
    .toast.show {
      opacity: 1;
      transform: translateY(0);
    }
    @media (max-width: 1220px) {
      .hero { grid-template-columns: 1fr; }
      .cockpit-grid { grid-template-columns: 1fr 1fr; }
      .layout { grid-template-columns: 1fr; }
      .analysis-layout { grid-template-columns: 1fr; }
      .chart-grid { grid-template-columns: 1fr; }
      .tables-grid { grid-template-columns: 1fr; }
    }
    @media (max-width: 900px) {
      .cockpit-grid { grid-template-columns: 1fr; }
      .filter-grid, .summary-card, .plan-grid, .action-grid { grid-template-columns: 1fr; }
      .plan-body { grid-template-columns: 1fr; }
      .analysis-stats, .manual-grid, .network-grid, .board-stats, .micro-grid { grid-template-columns: 1fr; }
      .market-row { grid-template-columns: 1fr; }
      .market-board-toolbar { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <section class="hero">
      <div class="panel headline">
        <div>
          <div class="section-kicker">Quant Desk / Research & Execution</div>
          <h1>中文交易工作台</h1>
          <p>这不是一个“只会刷日志”的页面。它会把实时行情、策略判断、风险预算和执行状态汇总成可操作的交易台。你可以在这里暂停/恢复、切换策略，并直接看到每个交易对当前是不是值得动手。</p>
        </div>
        <div class="hero-strip">
          <div class="badge" id="status-badge">加载中</div>
          <div class="badge" id="mode-badge">模式</div>
          <div class="badge" id="strategy-badge">策略</div>
        </div>
      </div>
      <div class="panel hero-note">
        <div>
          <div class="section-kicker">现在这套系统对你有什么用</div>
          <div class="big-value" id="hero-action">等待分析</div>
        </div>
        <div class="subline" id="hero-summary">系统会把“是否值得进场、为什么、风险有多大、被什么风控拦住”直接翻译成中文计划卡片，而不是只给你一堆信号名词。</div>
      </div>
    </section>

    <section class="panel cockpit-strip">
      <div class="title-row">
        <h2>启动状态 / 快速看盘</h2>
        <span class="muted" id="boot-updated">等待首轮同步</span>
      </div>
      <div class="cockpit-grid">
        <div class="status-card dark">
          <div class="metric-label">当前阶段</div>
          <div class="status-big" id="boot-stage">启动中</div>
          <div class="metric-sub" id="boot-detail">网页已经打开，正在等待行情、账户、榜单和计划卡同步。</div>
        </div>
        <div class="status-card">
          <div class="metric-label">行情状态</div>
          <div class="status-big" id="boot-market">预热中</div>
          <div class="metric-sub" id="boot-market-detail">还没有拿到足够的 K 线。</div>
        </div>
        <div class="status-card">
          <div class="metric-label">账户 / 私有流</div>
          <div class="status-big" id="boot-account">等待中</div>
          <div class="metric-sub" id="boot-account-detail">当前还没有账户侧同步摘要。</div>
        </div>
        <div class="status-card">
          <div class="metric-label">榜单覆盖</div>
          <div class="status-big" id="boot-board">0</div>
          <div class="metric-sub" id="boot-board-detail">还没有收到涨跌榜快照。</div>
        </div>
      </div>
      <div class="status-inline" id="transport-banner">如果你看到这里长时间不动，通常是浏览器拿到了旧页面缓存，或者当前会话还没完成第一轮状态刷新。</div>
      <div class="progress-wrap">
        <div class="progress-row">
          <span id="boot-progress-label">启动进度</span>
          <strong id="boot-progress-value">0%</strong>
        </div>
        <div class="progress-track">
          <div class="progress-fill" id="boot-progress-fill"></div>
        </div>
      </div>
      <div class="sync-strip">
        <div class="sync-chip">
          <strong>前端心跳</strong>
          <span id="client-heartbeat">前端还没开始跳动</span>
        </div>
        <div class="sync-chip">
          <strong>轻量同步</strong>
          <span id="client-last-lite">等待首轮轻量同步</span>
        </div>
        <div class="sync-chip">
          <strong>完整同步</strong>
          <span id="client-last-full">等待首轮完整同步</span>
        </div>
        <div class="sync-chip">
          <strong>前端错误</strong>
          <span id="client-last-error">当前还没有前端错误</span>
        </div>
      </div>
      <div class="pulse-strip" id="market-pulse"></div>
    </section>

    <div class="layout">
      <aside class="left-rail">
        <section class="panel">
          <div class="title-row">
            <h2>操作台</h2>
            <span class="muted" id="control-pending">控制队列 0</span>
          </div>
          <div class="control-stack">
            <div class="action-grid">
              <button class="action-btn secondary" id="pause-btn">暂停交易</button>
              <button class="action-btn ghost" id="resume-btn">恢复交易</button>
            </div>
            <div class="field">
              <label for="strategy-switch">切换策略</label>
              <select id="strategy-switch"><option value="">等待策略列表</option></select>
            </div>
            <button class="action-btn primary" id="switch-strategy-btn">应用策略切换</button>
            <div class="inline-note" id="control-help">暂停交易后，系统将停止新开仓；恢复后会继续处理新信号。保护模式不能直接从网页解除。</div>
          </div>
        </section>

        <section class="panel">
          <div class="title-row">
            <h2>控制回执</h2>
            <span class="muted">最近 20 条</span>
          </div>
          <div class="event-list" id="control-events"></div>
        </section>

        <section class="panel">
          <div class="title-row">
            <h2>手动下单</h2>
            <span class="muted" id="manual-mode-label">仅限 paper / testnet</span>
          </div>
          <div class="manual-stack">
            <div class="manual-grid">
              <div class="field">
                <label for="manual-symbol">交易对</label>
                <input id="manual-symbol" placeholder="例如 BTCUSDT">
              </div>
              <div class="field">
                <label for="manual-timeframe">分析周期</label>
                <select id="manual-timeframe"><option value="1m">1m</option></select>
              </div>
              <div class="field">
                <label for="manual-side">方向</label>
                <select id="manual-side">
                  <option value="BUY">买入</option>
                  <option value="SELL">卖出/平仓</option>
                </select>
              </div>
              <div class="field">
                <label for="manual-order-type">订单类型</label>
                <select id="manual-order-type">
                  <option value="MARKET">市价</option>
                  <option value="LIMIT">限价</option>
                </select>
              </div>
              <div class="field">
                <label for="manual-quantity">数量</label>
                <input id="manual-quantity" type="number" min="0" step="0.000001" placeholder="留空则按系统建议">
              </div>
              <div class="field">
                <label for="manual-price">限价</label>
                <input id="manual-price" type="number" min="0" step="0.000001" placeholder="限价单必填" disabled>
              </div>
            </div>
            <div class="action-grid">
              <button class="action-btn ghost" id="fill-from-analysis-btn">用当前分析填充</button>
              <button class="action-btn primary" id="manual-order-btn">提交手动单</button>
            </div>
            <div class="manual-note" id="manual-note">这块只对仿真盘和测试盘开放。买入单仍会经过仓位风控、交易规则校验、余额检查，并自动附带系统计算出的止损止盈；卖出单默认按现有持仓处理。</div>
          </div>
        </section>

        <section class="panel">
          <div class="title-row">
            <h2>核心概览</h2>
            <span class="muted">你现在该看什么</span>
          </div>
          <div class="summary-stack">
            <div class="summary-card">
              <div class="metric-card">
                <div class="metric-label">当前模式</div>
                <div class="metric-value" id="mode">-</div>
                <div class="metric-sub" id="active-strategy">-</div>
              </div>
              <div class="metric-card">
                <div class="metric-label">风控状态</div>
                <div class="metric-value" id="risk-status">-</div>
                <div class="metric-sub" id="risk-reason">-</div>
              </div>
              <div class="metric-card">
                <div class="metric-label">账户净值</div>
                <div class="metric-value" id="nav">-</div>
                <div class="metric-sub" id="nav-change">会话盈亏：-</div>
              </div>
              <div class="metric-card">
                <div class="metric-label">可用 USDT</div>
                <div class="metric-value" id="quote">-</div>
                <div class="metric-sub" id="today-pnl">今日已实现：-</div>
              </div>
            </div>
            <div class="micro-grid">
              <div class="metric-card">
                <div class="metric-label">上涨币数</div>
                <div class="metric-value" id="board-positive">-</div>
                <div class="metric-sub">当前榜单统计</div>
              </div>
              <div class="metric-card">
                <div class="metric-label">下跌币数</div>
                <div class="metric-value" id="board-negative">-</div>
                <div class="metric-sub">当前榜单统计</div>
              </div>
              <div class="metric-card">
                <div class="metric-label">市场均涨跌</div>
                <div class="metric-value" id="board-average">-</div>
                <div class="metric-sub" id="board-tracked">跟踪币种：-</div>
              </div>
            </div>
          </div>
        </section>

        <section class="panel network-card">
          <div class="title-row">
            <h2>Binance / Testnet 网络诊断</h2>
            <span class="muted" id="network-updated">等待检测</span>
          </div>
          <div class="network-summary" id="network-summary">系统会自动检查当前代理节点、DNS 解析、Binance 主站与 Testnet 的可达性，并把最可能的阻断原因翻译成中文。</div>
          <div class="network-grid">
            <div class="network-item">
              <div class="metric-label">当前节点 / 路由</div>
              <div class="metric-sub" id="network-server">-</div>
            </div>
            <div class="network-item">
              <div class="metric-label">DNS / Fake-IP</div>
              <div class="metric-sub" id="network-dns">-</div>
            </div>
          </div>
          <div class="title-row">
            <h3>端点检测</h3>
            <span class="muted">主站 / Testnet / 行情只读</span>
          </div>
          <div class="stack-list" id="network-endpoints"></div>
          <div class="title-row">
            <h3>建议你这样改</h3>
            <span class="muted">按顺序做</span>
          </div>
          <div class="stack-list" id="network-recommendations"></div>
          <div class="title-row">
            <h3>Shadowrocket 规则示例</h3>
            <span class="muted">把“非美国节点”换成你的策略组名</span>
          </div>
          <div class="snippet-box" id="network-snippets">等待生成规则示例</div>
        </section>
      </aside>

      <main class="main-rail">
        <section class="panel">
          <div class="title-row">
            <h2>视图筛选</h2>
            <span class="muted">筛选只影响展示，不会改动交易逻辑</span>
          </div>
          <div class="filter-grid">
            <div class="field">
              <label for="symbol-filter">交易对</label>
              <select id="symbol-filter"><option value="ALL">等待数据</option></select>
            </div>
            <div class="field">
              <label for="strategy-filter">策略</label>
              <select id="strategy-filter"><option value="ALL">等待数据</option></select>
            </div>
            <div class="field">
              <label for="timeframe-filter">周期</label>
              <select id="timeframe-filter"><option value="ALL">等待数据</option></select>
            </div>
            <div class="field">
              <label for="window-filter">时间窗口</label>
              <select id="window-filter">
                <option value="15">最近 15 分钟</option>
                <option value="60" selected>最近 60 分钟</option>
                <option value="240">最近 4 小时</option>
                <option value="1440">最近 24 小时</option>
                <option value="all">全部</option>
              </select>
            </div>
          </div>
        </section>

        <section class="analysis-layout">
          <section class="analysis-card">
            <div>
              <div class="section-kicker">点一下榜单，马上给你中文建议</div>
              <div class="analysis-title" id="analysis-symbol">等待选币</div>
              <div class="analysis-reason" id="analysis-summary">先从右侧涨幅榜选一个币，系统会拉取该币的实时 K 线，结合当前策略和风控，告诉你现在适不适合买、参考入场、止损止盈和风险预算。</div>
            </div>
            <div class="analysis-stats">
              <div class="analysis-stat">
                <div class="plan-stat-label">当前动作</div>
                <div class="plan-stat-value" id="analysis-action">-</div>
              </div>
              <div class="analysis-stat">
                <div class="plan-stat-label">参考入场</div>
                <div class="plan-stat-value" id="analysis-entry">-</div>
              </div>
              <div class="analysis-stat">
                <div class="plan-stat-label">建议数量</div>
                <div class="plan-stat-value" id="analysis-qty">-</div>
              </div>
              <div class="analysis-stat">
                <div class="plan-stat-label">止损</div>
                <div class="plan-stat-value" id="analysis-stop">-</div>
              </div>
              <div class="analysis-stat">
                <div class="plan-stat-label">止盈</div>
                <div class="plan-stat-value" id="analysis-take">-</div>
              </div>
              <div class="analysis-stat">
                <div class="plan-stat-label">24H 涨幅</div>
                <div class="plan-stat-value" id="analysis-change">-</div>
              </div>
              <div class="analysis-stat">
                <div class="plan-stat-label">名义价值</div>
                <div class="plan-stat-value" id="analysis-notional">-</div>
              </div>
              <div class="analysis-stat">
                <div class="plan-stat-label">预估亏损</div>
                <div class="plan-stat-value" id="analysis-risk">-</div>
              </div>
              <div class="analysis-stat">
                <div class="plan-stat-label">盈亏比</div>
                <div class="plan-stat-value" id="analysis-rr">-</div>
              </div>
            </div>
            <div class="analysis-advice" id="analysis-advice">当前还没有选中币种。你可以先看涨幅榜，再决定是否要让系统给出详细分析。</div>
          </section>

          <section class="panel market-board-card">
            <div class="title-row">
              <h2>全市场涨幅榜</h2>
              <span class="muted" id="market-board-meta">主流 USDT 现货 / 实时更新</span>
            </div>
            <div class="market-board-toolbar">
              <div class="field">
                <label for="market-board-search">搜索币种</label>
                <input id="market-board-search" placeholder="例如 DOGE、SOL、BTCUSDT">
              </div>
              <div class="field">
                <label for="market-board-mode">榜单模式</label>
                <select id="market-board-mode">
                  <option value="gainers">涨幅榜</option>
                  <option value="losers">跌幅榜</option>
                  <option value="volume">成交额榜</option>
                </select>
              </div>
              <div class="inline-note">点一下榜单，就会生成中文计划</div>
            </div>
            <div class="board-stats">
              <div class="board-stat">
                <div class="metric-label">跟踪币种</div>
                <div class="plan-stat-value" id="market-board-tracked">-</div>
              </div>
              <div class="board-stat">
                <div class="metric-label">上涨 / 下跌</div>
                <div class="plan-stat-value" id="market-board-breadth">-</div>
              </div>
              <div class="board-stat">
                <div class="metric-label">平均涨跌</div>
                <div class="plan-stat-value" id="market-board-average">-</div>
              </div>
            </div>
            <div class="market-board-scroll" id="market-board"></div>
          </section>
        </section>

        <section class="panel">
          <div class="title-row">
            <h2>交易计划板</h2>
            <span class="muted" id="plan-count">0 张计划卡</span>
          </div>
          <div class="plan-grid" id="plan-grid"></div>
        </section>

        <section class="chart-grid">
          <div class="chart-card">
            <div class="title-row">
              <h3>权益曲线</h3>
              <span class="muted" id="equity-points">0 个点</span>
            </div>
            <div class="chart" id="equity-chart"></div>
          </div>
          <div class="chart-card">
            <div class="title-row">
              <h3>会话盈亏</h3>
              <span class="muted" id="pnl-points">0 个点</span>
            </div>
            <div class="chart" id="pnl-chart"></div>
          </div>
          <div class="chart-card">
            <div class="title-row">
              <h3>价格 / K线简图</h3>
              <span class="muted" id="price-series-label">-</span>
            </div>
            <div class="chart" id="price-chart"></div>
          </div>
        </section>

        <section class="tables-grid">
          <div class="table-card">
            <div class="title-row"><h3>当前持仓</h3><span class="muted" id="position-count">0 个持仓</span></div>
            <table id="positions-table"></table>
          </div>
          <div class="table-card">
            <div class="title-row"><h3>最近成交</h3><span class="muted" id="fill-count">0 条</span></div>
            <table id="fills-table"></table>
          </div>
          <div class="table-card">
            <div class="title-row"><h3>最近订单</h3><span class="muted" id="order-count">0 条</span></div>
            <table id="orders-table"></table>
          </div>
          <div class="table-card">
            <div class="title-row"><h3>最近信号</h3><span class="muted" id="signal-count">0 条</span></div>
            <table id="signals-table"></table>
          </div>
          <div class="table-card">
            <div class="title-row"><h3>订单时间线</h3><span class="muted" id="timeline-count">0 条</span></div>
            <table id="timeline-table"></table>
          </div>
          <div class="table-card">
            <div class="title-row"><h3>连接健康状态</h3><span class="muted" id="connection-count">0 条</span></div>
            <table id="connection-table"></table>
          </div>
          <div class="table-card full-width">
            <div class="title-row"><h3>风控事件</h3><span class="muted" id="risk-count">0 条</span></div>
            <table id="risk-table"></table>
          </div>
        </section>
      </main>
    </div>
  </div>

  <div class="toast" id="toast"></div>

  <script>
    const filters = {
      symbol: 'ALL',
      strategy: 'ALL',
      timeframe: 'ALL',
      window: '60'
    };

    let latestData = null;
    let selectedAnalysis = null;
    let selectedBoardMode = 'gainers';
    let refreshFailures = 0;
    let liteRefreshInFlight = false;
    let fullRefreshInFlight = false;
    let clientHeartbeatCount = 0;
    let lastLiteRevision = 0;
    let lastFullRevision = 0;

    function asMoney(value) {
      if (value === null || value === undefined || Number.isNaN(Number(value))) return '-';
      return Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    function asQty(value) {
      if (value === null || value === undefined || Number.isNaN(Number(value))) return '-';
      return Number(value).toFixed(6);
    }

    function asPct(value) {
      if (value === null || value === undefined || Number.isNaN(Number(value))) return '-';
      const number = Number(value);
      const sign = number > 0 ? '+' : '';
      return `${sign}${number.toFixed(2)}%`;
    }

    function asRatio(value) {
      if (value === null || value === undefined || Number.isNaN(Number(value))) return '-';
      return `${Number(value).toFixed(2)} R`;
    }

    function escapeHtml(text) {
      return String(text ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;');
    }

    function normalizeSymbol(value) {
      return String(value || '').replaceAll('/', '').toUpperCase();
    }

    function normalizeStrategy(value) {
      return String(value || '').trim() || 'unknown';
    }

    function displaySymbol(value) {
      const normalized = normalizeSymbol(value);
      if (normalized.endsWith('USDT')) {
        return `${normalized.slice(0, -4)}/USDT`;
      }
      return normalized;
    }

    function supportsManualOrders(mode) {
      return ['paper', 'testnet'].includes(String(mode || '').toLowerCase());
    }

    function translateChannel(value) {
      const map = {
        engine: '交易引擎',
        market_data: '行情通道',
        user_stream: '账户流'
      };
      const key = String(value || '').toLowerCase();
      return map[key] || value || '-';
    }

    function translateMode(value) {
      const map = {
        backtest: '回测',
        paper: '仿真盘',
        testnet: '测试盘',
        monitor: '主网观察',
        live: '实盘(禁用)',
        unknown: '未知'
      };
      const key = String(value || '').toLowerCase();
      return map[key] || value || '-';
    }

    function translateStatus(value) {
      const map = {
        starting: '启动中',
        initialized: '已初始化',
        ready: '就绪',
        streaming: '实时流中',
        'streaming+user-stream': '行情与账户流',
        'streaming+synced': '已同步',
        active: '正常',
        paused: '已暂停',
        protect: '保护模式',
        new: '新建',
        partially_filled: '部分成交',
        filled: '已成交',
        canceled: '已撤单',
        rejected: '已拒绝',
        expired: '已过期',
        subscribed: '已订阅',
        connecting: '连接中',
        connected: '已连接',
        reconnecting: '重连中',
        bootstrap: '引导同步',
        ok: '可达',
        warning: '警告',
        blocked: '受限',
        error: '错误',
        unknown: '未知'
      };
      const key = String(value || '').toLowerCase();
      return map[key] || value || '-';
    }

    function translateSignal(value) {
      const map = {
        BUY: '买入',
        SELL: '卖出',
        FLAT: '平仓',
        HOLD: '观望'
      };
      return map[String(value || '').toUpperCase()] || value || '-';
    }

    function translateSide(value) {
      const map = {
        BUY: '买入',
        SELL: '卖出'
      };
      return map[String(value || '').toUpperCase()] || value || '-';
    }

    function translateStrategy(value) {
      const map = {
        ema_trend: 'EMA 趋势',
        rsi_bbands_mean_reversion: 'RSI + 布林带均值回归',
        unknown: '未知策略'
      };
      const key = String(value || '').trim();
      return map[key] || value || '-';
    }

    function translateRiskEventType(value) {
      const map = {
        risk_block: '风控拦截',
        protect_mode: '保护模式',
        pause: '暂停交易',
        external_lock_update: '外部锁仓更新'
      };
      const key = String(value || '').toLowerCase();
      return map[key] || value || '-';
    }

    function translatePlanStatus(value) {
      const map = {
        planned: '可执行计划',
        blocked: '风控拦截',
        position: '已有持仓',
        watch: '继续观察'
      };
      const key = String(value || '').toLowerCase();
      return map[key] || value || '-';
    }

    function formatSyncTime(value) {
      if (!value) return '等待同步';
      const text = String(value);
      if (text.includes('T')) return text.replace('T', ' ').slice(0, 19);
      return text.slice(0, 19);
    }

    function updateHeartbeat() {
      clientHeartbeatCount += 1;
      document.getElementById('client-heartbeat').textContent = `前端已刷新 ${clientHeartbeatCount} 次`;
    }

    function rememberSync(kind, data) {
      const label = `${kind === 'lite' ? '轻量' : '完整'}同步：修订 ${Number(data.snapshot_revision || 0)} / ${formatSyncTime(data.market_board?.updated_at || data.account?.timestamp)}`;
      if (kind === 'lite') {
        lastLiteRevision = Number(data.snapshot_revision || lastLiteRevision || 0);
        document.getElementById('client-last-lite').textContent = label;
      } else {
        lastFullRevision = Number(data.snapshot_revision || lastFullRevision || 0);
        document.getElementById('client-last-full').textContent = label;
      }
    }

    function reportClientError(context, error) {
      const reason = error?.message || String(error || '未知错误');
      document.getElementById('client-last-error').textContent = `${context}：${reason}`;
      setTransportBanner(
        `前端在“${context}”阶段遇到错误：${reason}。页面会继续尝试刷新，其余模块不会一起卡死。`,
        'error'
      );
    }

    function guardRender(context, renderer, fallbackValue = null) {
      try {
        return renderer();
      } catch (error) {
        reportClientError(context, error);
        return fallbackValue;
      }
    }

    function renderBootStatus(data) {
      const board = data.market_board || {};
      const rows = board.rows || [];
      const rowCount = Number(board.row_count || rows.length || 0);
      const endpoints = data.network_diagnostics?.endpoints || [];
      const okEndpoints = endpoints.filter(item => item.status === 'ok');
      const hasAccountValue = Number(data.account?.net_asset_value || 0) > 0;
      const hasPlans = (data.trade_plans || []).length > 0;
      const signalCount = (data.recent_signals || []).length;
      let progress = 10;
      if (String(data.connection_status || '').includes('ready') || String(data.connection_status || '').includes('stream')) progress += 20;
      if (rowCount) progress += 30;
      if (okEndpoints.length) progress += 20;
      if (hasPlans || signalCount) progress += 20;
      progress = Math.min(100, progress);
      let stage = '启动中';
      let detail = '网页已经打开，正在等待第一轮状态刷新。';
      if (rowCount && hasPlans) {
        stage = '已联机';
        detail = '行情、榜单和计划卡都已就绪，可以开始看盘和点币分析。';
      } else if (rowCount) {
        stage = '预热中';
        detail = '榜单已经到了，策略和计划卡还在继续预热。';
      } else if (String(data.connection_status || '').includes('stream')) {
        stage = '接流中';
        detail = '实时流已经建立，榜单和计划卡会继续刷新。';
      }
      document.getElementById('boot-stage').textContent = stage;
      document.getElementById('boot-detail').textContent = detail;
      document.getElementById('boot-progress-fill').style.width = `${progress}%`;
      document.getElementById('boot-progress-value').textContent = `${progress}%`;
      document.getElementById('boot-progress-label').textContent = progress >= 100 ? '启动完成' : '启动进度';
      document.getElementById('boot-updated').textContent = board.updated_at
        ? `榜单更新于 ${String(board.updated_at).replace('T', ' ').slice(0, 19)}`
        : '等待首轮同步';
      document.getElementById('boot-market').textContent = rowCount ? '已连接' : '预热中';
      document.getElementById('boot-market-detail').textContent = rowCount
        ? `当前榜单已有 ${rowCount} 个币，可直接点榜分析。`
        : '还没有拿到市场榜单快照。';
      document.getElementById('boot-account').textContent = hasAccountValue ? '已同步' : translateMode(data.mode) === '测试盘' ? '待认证' : '模拟中';
      document.getElementById('boot-account-detail').textContent = okEndpoints.length
        ? `网络诊断已通过 ${okEndpoints.length} 个关键端点。`
        : '账户侧还没有形成可展示的同步摘要。';
      document.getElementById('boot-board').textContent = String(rowCount || 0);
      document.getElementById('boot-board-detail').textContent = rowCount
        ? `当前 ${document.getElementById('market-board-mode').selectedOptions[0]?.textContent || '榜单'} 已经可用。`
        : (board.message || '还没有收到涨跌榜快照。');
    }

    function renderMarketPulse(data) {
      const target = document.getElementById('market-pulse');
      const board = data.market_board || {};
      const sections = board.sections || {};
      const rows = (sections[selectedBoardMode] || board.rows || []).slice(0, 8);
      if (!rows.length) {
        target.innerHTML = '<div class="pulse-chip"><div class="symbol">等待市场快照</div><div class="meta">行情榜单还没到，通常再等几秒就会进来。</div></div>';
        return;
      }
      const activeSymbol = normalizeSymbol(selectedAnalysis?.symbol || '');
      target.innerHTML = rows.map(row => `
        <div class="pulse-chip ${normalizeSymbol(row.symbol) === activeSymbol ? 'active' : ''}" data-pulse-symbol="${escapeHtml(row.symbol)}">
          <div class="symbol">${escapeHtml(row.display_symbol || displaySymbol(row.symbol))}</div>
          <div class="meta">
            ${escapeHtml(asPct(row.price_change_percent))} / 价 ${escapeHtml(asMoney(row.last_price))}<br>
            成交额 ${escapeHtml(asMoney(row.quote_volume))} USDT
          </div>
        </div>
      `).join('');
      target.querySelectorAll('[data-pulse-symbol]').forEach(node => {
        node.addEventListener('click', () => requestSymbolAnalysis(node.getAttribute('data-pulse-symbol')));
      });
    }

    function toMillis(value) {
      const parsed = Date.parse(value || '');
      return Number.isNaN(parsed) ? 0 : parsed;
    }

    function withinWindow(value) {
      if (filters.window === 'all') return true;
      const timestamp = toMillis(value);
      if (!timestamp) return true;
      const deltaMs = Number(filters.window) * 60 * 1000;
      return Date.now() - timestamp <= deltaMs;
    }

    function pickPillClass(state) {
      const lower = String(state || '').toLowerCase();
      if (['protect', 'reconnecting', 'error', 'rejected', 'expired', 'blocked'].some(item => lower.includes(item))) return 'danger';
      if (['paused', 'warn', 'sell', 'flat', 'canceled', 'position'].some(item => lower.includes(item))) return 'warn';
      return 'ok';
    }

    function renderRows(tableId, columns, rows, emptyText) {
      const table = document.getElementById(tableId);
      const head = '<tr>' + columns.map(col => `<th>${escapeHtml(col.label)}</th>`).join('') + '</tr>';
      if (!rows || rows.length === 0) {
        table.innerHTML = head + `<tr><td colspan="${columns.length}" class="muted">${escapeHtml(emptyText)}</td></tr>`;
        return;
      }
      const body = rows.map(row => '<tr>' + columns.map(col => `<td>${col.render(row)}</td>`).join('') + '</tr>').join('');
      table.innerHTML = head + body;
    }

    function ensureOptions(selectId, options, selectedValue) {
      const select = document.getElementById(selectId);
      const previous = select.value || selectedValue;
      select.innerHTML = options.map(option => `<option value="${escapeHtml(option.value)}">${escapeHtml(option.label)}</option>`).join('');
      select.value = options.some(option => option.value === previous) ? previous : selectedValue;
    }

    function drawLineChart(targetId, points, valueAccessor, color, fillColor) {
      const target = document.getElementById(targetId);
      if (!points || points.length === 0) {
        target.innerHTML = '<div class="chart-empty">当前筛选窗口内没有可显示的数据。</div>';
        return;
      }
      const width = 520;
      const height = 220;
      const padX = 20;
      const padY = 18;
      const values = points.map(valueAccessor);
      const min = Math.min(...values);
      const max = Math.max(...values);
      const spread = max - min || 1;
      const xStep = points.length > 1 ? (width - padX * 2) / (points.length - 1) : 0;
      const coords = points.map((point, index) => {
        const x = padX + xStep * index;
        const y = height - padY - ((valueAccessor(point) - min) / spread) * (height - padY * 2);
        return [x, y];
      });
      const linePath = coords.map((coord, index) => `${index === 0 ? 'M' : 'L'} ${coord[0]} ${coord[1]}`).join(' ');
      const areaPath = `${linePath} L ${coords[coords.length - 1][0]} ${height - padY} L ${coords[0][0]} ${height - padY} Z`;
      const latest = values[values.length - 1];
      const earliest = values[0];
      const delta = latest - earliest;
      target.innerHTML = `
        <svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true">
          <path d="${areaPath}" fill="${fillColor}" opacity="0.86"></path>
          <path d="${linePath}" fill="none" stroke="${color}" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"></path>
          <circle cx="${coords[coords.length - 1][0]}" cy="${coords[coords.length - 1][1]}" r="4.5" fill="${color}"></circle>
          <text x="${padX}" y="${padY}" fill="#596461" font-size="11">${escapeHtml(asMoney(min))}</text>
          <text x="${width - 90}" y="${padY}" fill="#596461" font-size="11">${escapeHtml(asMoney(max))}</text>
          <text x="${width - 128}" y="${height - 12}" fill="${delta >= 0 ? '#095b49' : '#a33026'}" font-size="11">变化 ${escapeHtml(asMoney(delta))}</text>
        </svg>
      `;
    }

    function drawPriceChart(targetId, points) {
      drawLineChart(targetId, points, point => Number(point.close || 0), '#095b49', 'rgba(9,91,73,0.13)');
    }

    function filterBySymbol(rows, extractor) {
      if (filters.symbol === 'ALL') return rows;
      return rows.filter(row => normalizeSymbol(extractor(row)) === filters.symbol);
    }

    function filterByStrategy(rows, extractor) {
      if (filters.strategy === 'ALL') return rows;
      return rows.filter(row => normalizeStrategy(extractor(row)) === filters.strategy);
    }

    function deriveTimeframeOptions(data, selectedSymbol) {
      const keys = Object.keys(data.price_history || {});
      const timeframes = new Set(['ALL']);
      keys.forEach(key => {
        const [symbol, timeframe] = key.split('|');
        if (selectedSymbol === 'ALL' || symbol === selectedSymbol) {
          timeframes.add(timeframe);
        }
      });
      return Array.from(timeframes).map(value => ({ value, label: value === 'ALL' ? '全部周期' : value }));
    }

    function syncFilterControls(data) {
      const symbols = new Set(['ALL']);
      (data.tracked_symbols || []).forEach(symbol => symbols.add(normalizeSymbol(symbol)));
      Object.keys(data.positions || {}).forEach(symbol => symbols.add(normalizeSymbol(symbol)));
      (data.recent_signals || []).forEach(row => symbols.add(normalizeSymbol(row.symbol)));
      (data.recent_orders || []).forEach(row => symbols.add(normalizeSymbol(row.symbol)));
      (data.recent_fills || []).forEach(row => symbols.add(normalizeSymbol(row.symbol)));
      (data.trade_plans || []).forEach(row => symbols.add(normalizeSymbol(row.symbol)));

      const strategies = new Set(['ALL']);
      if (data.active_strategy) strategies.add(normalizeStrategy(data.active_strategy));
      (data.recent_signals || []).forEach(row => strategies.add(normalizeStrategy(row.strategy_name)));
      (data.recent_orders || []).forEach(row => strategies.add(normalizeStrategy(row.metadata?.strategy)));
      (data.trade_plans || []).forEach(row => strategies.add(normalizeStrategy(row.strategy_name)));

      ensureOptions(
        'symbol-filter',
        Array.from(symbols).map(value => ({ value, label: value === 'ALL' ? '全部交易对' : value })),
        filters.symbol
      );
      filters.symbol = document.getElementById('symbol-filter').value || 'ALL';

      ensureOptions(
        'strategy-filter',
        Array.from(strategies).map(value => ({ value, label: value === 'ALL' ? '全部策略' : translateStrategy(value) })),
        filters.strategy
      );
      filters.strategy = document.getElementById('strategy-filter').value || 'ALL';

      ensureOptions('timeframe-filter', deriveTimeframeOptions(data, filters.symbol), filters.timeframe);
      filters.timeframe = document.getElementById('timeframe-filter').value || 'ALL';
    }

    function syncManualControls(data) {
      const tracked = new Set(data.tracked_timeframes || []);
      tracked.add('1m');
      tracked.add('5m');
      ensureOptions(
        'manual-timeframe',
        Array.from(tracked).map(value => ({ value, label: value })),
        document.getElementById('manual-timeframe').value || data.tracked_timeframes?.[0] || '1m'
      );

      const manualEnabled = supportsManualOrders(data.mode);
      document.getElementById('manual-order-btn').disabled = !manualEnabled;
      document.getElementById('fill-from-analysis-btn').disabled = !selectedAnalysis;
      document.getElementById('manual-mode-label').textContent = manualEnabled ? `当前 ${translateMode(data.mode)} 可下单` : '仅限 paper / testnet';
      document.getElementById('manual-note').textContent = manualEnabled
        ? '手动单仍会经过风控、规则校验、余额检查。买入会自动带上系统计算的止损止盈，卖出则默认按现有持仓减仓或平仓。'
        : '当前模式只允许分析，不允许网页手动下单。想手动单测，请切到仿真盘或测试盘。';
    }

    function renderNetworkDiagnostics(data) {
      const diagnostics = data.network_diagnostics || {};
      document.getElementById('network-updated').textContent = diagnostics.updated_at
        ? `更新于 ${String(diagnostics.updated_at).replace('T', ' ').slice(0, 19)}`
        : '等待检测';
      document.getElementById('network-summary').textContent = diagnostics.summary || '暂时还没有拿到网络诊断结果。';

      const server = diagnostics.shadowrocket?.selected_server || '未识别到 Shadowrocket 当前节点';
      const route = diagnostics.shadowrocket?.routing_method || '未知';
      document.getElementById('network-server').textContent = `${server} / 路由模式：${route}`;

      const fakeIp = diagnostics.dns?.fake_ip_detected ? '已检测到 Binance 域名走 Fake-IP' : '当前未检测到明显 Fake-IP 问题';
      const nameserver = diagnostics.dns?.primary_nameserver || '-';
      document.getElementById('network-dns').textContent = `${fakeIp} / 主 DNS：${nameserver}`;

      const endpoints = diagnostics.endpoints || [];
      const endpointTarget = document.getElementById('network-endpoints');
      endpointTarget.innerHTML = endpoints.length
        ? endpoints.map(item => `
            <div class="stack-row">
              <strong>${escapeHtml(item.name || '-')}</strong><br>
              状态：${escapeHtml(translateStatus(item.status || '-'))}
              ${item.http_status ? ` / HTTP ${escapeHtml(String(item.http_status))}` : ''}
              ${item.message ? `<br>${escapeHtml(item.message)}` : ''}
            </div>
          `).join('')
        : '<div class="stack-row">当前还没有端点检测结果。</div>';

      const recommendations = diagnostics.recommendations || [];
      const recommendationTarget = document.getElementById('network-recommendations');
      recommendationTarget.innerHTML = recommendations.length
        ? recommendations.map((item, index) => `<div class="stack-row">${index + 1}. ${escapeHtml(item)}</div>`).join('')
        : '<div class="stack-row">当前没有额外建议。</div>';

      const snippets = diagnostics.rule_snippets || [];
      document.getElementById('network-snippets').textContent = snippets.length
        ? snippets.join('\n')
        : '等待生成规则示例';
    }

    function renderMarketBoard(data) {
      const board = data.market_board || {};
      const sections = board.sections || {};
      const boardRows = sections[selectedBoardMode] || board.rows || [];
      const searchQuery = String(document.getElementById('market-board-search')?.value || '').trim().toUpperCase();
      const allRows = boardRows;
      const rows = !searchQuery
        ? allRows
        : allRows.filter(row => {
            const text = `${row.symbol || ''} ${row.display_symbol || ''} ${row.base_asset || ''}`.toUpperCase();
            return text.includes(searchQuery);
          });
      const target = document.getElementById('market-board');
      const stats = board.stats || {};
      document.getElementById('market-board-tracked').textContent = String(stats.tracked_pairs || 0);
      document.getElementById('market-board-breadth').textContent = `${stats.positive_pairs || 0} / ${stats.negative_pairs || 0}`;
      document.getElementById('market-board-average').textContent = asPct(stats.average_change_percent || 0);
      document.getElementById('market-board-meta').textContent = board.updated_at
        ? `更新于 ${String(board.updated_at).replace('T', ' ').slice(0, 19)} / 来源 ${board.source || '-'} / ${document.getElementById('market-board-mode').selectedOptions[0]?.textContent || '榜单'} / 显示 ${rows.length} 个`
        : '主流 USDT 现货 / 实时更新';
      if (!rows.length) {
        target.innerHTML = searchQuery
          ? '<div class="event-item"><strong>没有找到匹配的币</strong><span>试试输入基础币名、交易对全称，或者清空搜索框后重新选择。</span></div>'
          : '<div class="event-item"><strong>涨幅榜暂时不可用</strong><span>如果当前网络只能访问部分 Binance 域名，这里会短暂为空；系统恢复后会自动更新。</span></div>';
        return;
      }
      const activeSymbol = normalizeSymbol(selectedAnalysis?.symbol || '');
      target.innerHTML = rows.map((row, index) => `
        <div class="market-row ${normalizeSymbol(row.symbol) === activeSymbol ? 'active' : ''}" data-symbol="${escapeHtml(row.symbol)}">
          <div>
            <div class="market-symbol">${index + 1}. ${escapeHtml(row.display_symbol || displaySymbol(row.symbol))}</div>
            <div class="market-sub">24h 成交额 ${escapeHtml(asMoney(row.quote_volume))} USDT</div>
          </div>
          <div>
            <div class="market-symbol ${Number(row.price_change_percent || 0) >= 0 ? 'positive' : 'negative'}">${escapeHtml(asPct(row.price_change_percent))}</div>
            <div class="market-sub">最新价 ${escapeHtml(asMoney(row.last_price))}</div>
          </div>
          <div>
            <div class="market-symbol">${escapeHtml(asMoney(row.high_price))}</div>
            <div class="market-sub">24h 高点</div>
          </div>
          <div>
            <button class="table-action-btn" data-analyze-symbol="${escapeHtml(row.symbol)}">实时分析</button>
          </div>
        </div>
      `).join('');
      target.querySelectorAll('[data-analyze-symbol]').forEach(button => {
        button.addEventListener('click', event => {
          event.stopPropagation();
          requestSymbolAnalysis(button.getAttribute('data-analyze-symbol'));
        });
      });
      target.querySelectorAll('.market-row').forEach(row => {
        row.addEventListener('click', () => requestSymbolAnalysis(row.getAttribute('data-symbol')));
      });
    }

    function renderAnalysisCard() {
      if (!selectedAnalysis) {
        document.getElementById('analysis-symbol').textContent = '等待选币';
        document.getElementById('analysis-summary').textContent = '先从右侧涨幅榜选一个币，系统会拉取该币的实时 K 线，结合当前策略和风控，告诉你现在适不适合买、参考入场、止损止盈和风险预算。';
        document.getElementById('analysis-action').textContent = '-';
        document.getElementById('analysis-entry').textContent = '-';
        document.getElementById('analysis-qty').textContent = '-';
        document.getElementById('analysis-stop').textContent = '-';
        document.getElementById('analysis-take').textContent = '-';
        document.getElementById('analysis-change').textContent = '-';
        document.getElementById('analysis-notional').textContent = '-';
        document.getElementById('analysis-risk').textContent = '-';
        document.getElementById('analysis-rr').textContent = '-';
        document.getElementById('analysis-advice').textContent = '当前还没有选中币种。你可以先看涨幅榜，再决定是否要让系统给出详细分析。';
        return;
      }
      document.getElementById('analysis-symbol').textContent = `${displaySymbol(selectedAnalysis.symbol)} / ${selectedAnalysis.timeframe}`;
      document.getElementById('analysis-summary').textContent = selectedAnalysis.summary || selectedAnalysis.reason || '暂无摘要';
      document.getElementById('analysis-action').textContent = `${translatePlanStatus(selectedAnalysis.status)} / ${translateSignal(selectedAnalysis.signal_type)}`;
      document.getElementById('analysis-entry').textContent = asMoney(selectedAnalysis.entry_price);
      document.getElementById('analysis-qty').textContent = asQty(selectedAnalysis.quantity);
      document.getElementById('analysis-stop').textContent = asMoney(selectedAnalysis.stop_loss);
      document.getElementById('analysis-take').textContent = asMoney(selectedAnalysis.take_profit);
      document.getElementById('analysis-change').textContent = asPct(selectedAnalysis.change_24h_pct);
      document.getElementById('analysis-notional').textContent = asMoney(selectedAnalysis.notional_value);
      document.getElementById('analysis-risk').textContent = asMoney(selectedAnalysis.risk_amount);
      document.getElementById('analysis-rr').textContent = asRatio(selectedAnalysis.risk_reward_ratio);
      document.getElementById('analysis-advice').textContent = `${selectedAnalysis.advice || ''}${selectedAnalysis.blocked_reasons?.length ? ` 风控原因：${selectedAnalysis.blocked_reasons.join('；')}` : ''}`;
      document.getElementById('fill-from-analysis-btn').disabled = false;
    }

    function applyAnalysisToManualForm() {
      if (!selectedAnalysis) {
        showToast('还没有选中实时分析结果。');
        return;
      }
      document.getElementById('manual-symbol').value = normalizeSymbol(selectedAnalysis.symbol);
      document.getElementById('manual-timeframe').value = selectedAnalysis.timeframe || '1m';
      document.getElementById('manual-side').value = selectedAnalysis.signal_type === 'BUY' ? 'BUY' : 'SELL';
      document.getElementById('manual-order-type').value = 'MARKET';
      document.getElementById('manual-quantity').value = selectedAnalysis.quantity ? Number(selectedAnalysis.quantity).toFixed(6) : '';
      document.getElementById('manual-price').value = selectedAnalysis.entry_price ? Number(selectedAnalysis.entry_price).toFixed(6) : '';
      showToast(`已把 ${displaySymbol(selectedAnalysis.symbol)} 的分析结果填入手动下单面板。`);
    }

    function applyDataFilters(data) {
      const filteredSignals = filterByStrategy(
        filterBySymbol((data.recent_signals || []).filter(row => withinWindow(row.timestamp)), row => row.symbol),
        row => row.strategy_name
      );

      const filteredOrders = filterByStrategy(
        filterBySymbol((data.recent_orders || []).filter(row => withinWindow(row.updated_at)), row => row.symbol),
        row => row.metadata?.strategy
      );

      const filteredFills = filterBySymbol(
        filterByStrategy((data.recent_fills || []).filter(row => withinWindow(row.timestamp)), row => row.symbol),
        row => row.metadata?.strategy
      );

      const filteredTimeline = filterByStrategy(
        filterBySymbol((data.order_timeline || []).filter(row => withinWindow(row.timestamp)), row => row.symbol),
        row => row.strategy_name
      );

      const filteredRisk = filterBySymbol(
        (data.risk_events || []).filter(row => withinWindow(row.timestamp)),
        row => row.details?.symbol || ''
      );

      const filteredConnections = (data.connection_events || []).filter(row => withinWindow(row.timestamp));

      const filteredPlans = filterByStrategy(
        filterBySymbol((data.trade_plans || []), row => row.symbol),
        row => row.strategy_name
      ).filter(row => filters.timeframe === 'ALL' || row.timeframe === filters.timeframe);

      const priceSeriesKey = Object.keys(data.price_history || {}).find(key => {
        const [symbol, timeframe] = key.split('|');
        const symbolMatch = filters.symbol === 'ALL' || symbol === filters.symbol;
        const timeframeMatch = filters.timeframe === 'ALL' || timeframe === filters.timeframe;
        return symbolMatch && timeframeMatch;
      });
      const filteredPriceSeries = priceSeriesKey ? (data.price_history[priceSeriesKey] || []).filter(row => withinWindow(row.timestamp)) : [];
      const filteredEquity = (data.equity_history || []).filter(row => withinWindow(row.timestamp));

      return {
        filteredSignals,
        filteredOrders,
        filteredFills,
        filteredTimeline,
        filteredRisk,
        filteredConnections,
        filteredPlans,
        filteredPriceSeries,
        filteredEquity,
        priceSeriesKey
      };
    }

    function updateSummary(data, filtered) {
      document.getElementById('mode').textContent = translateMode(data.mode);
      document.getElementById('mode-badge').textContent = translateMode(data.mode || '模式');
      document.getElementById('active-strategy').textContent = `当前策略：${translateStrategy(data.active_strategy)}`;
      document.getElementById('strategy-badge').textContent = translateStrategy(data.active_strategy || 'unknown');
      document.getElementById('nav').textContent = asMoney(data.account?.net_asset_value);
      document.getElementById('quote').textContent = asMoney(data.account?.available_quote_balance);
      document.getElementById('risk-status').textContent = translateStatus(data.risk_state?.status);
      document.getElementById('risk-reason').textContent = data.risk_state?.reason || '当前没有风控阻断';
      document.getElementById('status-badge').textContent = translateStatus(data.connection_status || 'unknown');
      document.getElementById('status-badge').className = `badge ${pickPillClass(data.risk_state?.status || data.connection_status)}`;
      document.getElementById('board-positive').textContent = String(data.market_board?.stats?.positive_pairs || 0);
      document.getElementById('board-negative').textContent = String(data.market_board?.stats?.negative_pairs || 0);
      document.getElementById('board-average').textContent = asPct(data.market_board?.stats?.average_change_percent || 0);
      document.getElementById('board-tracked').textContent = `跟踪币种：${data.market_board?.stats?.tracked_pairs || 0}`;

      const sessionPnl = filtered.filteredEquity.length ? Number(filtered.filteredEquity[filtered.filteredEquity.length - 1].session_pnl || 0) : 0;
      document.getElementById('nav-change').textContent = `会话盈亏：${asMoney(sessionPnl)}`;
      document.getElementById('today-pnl').textContent = `今日已实现：${asMoney(data.risk_state?.daily_realized_pnl)}`;
      document.getElementById('equity-points').textContent = `${filtered.filteredEquity.length} 个点`;
      document.getElementById('pnl-points').textContent = `${filtered.filteredEquity.length} 个点`;
      document.getElementById('price-series-label').textContent = filtered.priceSeriesKey ? filtered.priceSeriesKey.replace('|', ' / ') : '当前筛选下没有匹配序列';
      const positionStats = data.position_stats || {};
      const displayedPositions = Number(positionStats.displayed_count || Object.values(data.positions || {}).filter(row => Number(row.quantity || 0) > 0).length);
      const openPositions = Number(positionStats.open_count || displayedPositions);
      const hiddenPositions = Number(positionStats.hidden_count || 0);
      document.getElementById('position-count').textContent = hiddenPositions > 0
        ? `显示 ${displayedPositions} / ${openPositions} 个持仓`
        : `${openPositions} 个持仓`;
      document.getElementById('fill-count').textContent = `${filtered.filteredFills.length} 条`;
      document.getElementById('order-count').textContent = `${filtered.filteredOrders.length} 条`;
      document.getElementById('signal-count').textContent = `${filtered.filteredSignals.length} 条`;
      document.getElementById('timeline-count').textContent = `${filtered.filteredTimeline.length} 条`;
      document.getElementById('connection-count').textContent = `${filtered.filteredConnections.length} 条`;
      document.getElementById('risk-count').textContent = `${filtered.filteredRisk.length} 条`;
      document.getElementById('plan-count').textContent = `${filtered.filteredPlans.length} 张计划卡`;
      document.getElementById('control-pending').textContent = `控制队列 ${Number(data.control_state?.pending_count || 0)}`;

      const mainPlan = filtered.filteredPlans[0] || data.trade_plans?.[0];
      if (mainPlan) {
        document.getElementById('hero-action').textContent = `${mainPlan.symbol} ${translatePlanStatus(mainPlan.status)}`;
        document.getElementById('hero-summary').textContent = `${translateStrategy(mainPlan.strategy_name)} / ${mainPlan.timeframe}：${mainPlan.reason}`;
      } else {
        document.getElementById('hero-action').textContent = '等待分析';
        document.getElementById('hero-summary').textContent = '当前还没有形成可读的交易计划，通常是因为刚启动、数据预热不足，或当前窗口下没有匹配交易对。';
      }
    }

    function renderLiteSummary(data) {
      document.getElementById('mode').textContent = translateMode(data.mode);
      document.getElementById('mode-badge').textContent = translateMode(data.mode || '模式');
      document.getElementById('active-strategy').textContent = `当前策略：${translateStrategy(data.active_strategy)}`;
      document.getElementById('strategy-badge').textContent = translateStrategy(data.active_strategy || 'unknown');
      document.getElementById('nav').textContent = asMoney(data.account?.net_asset_value);
      document.getElementById('quote').textContent = asMoney(data.account?.available_quote_balance);
      document.getElementById('risk-status').textContent = translateStatus(data.risk_state?.status);
      document.getElementById('risk-reason').textContent = data.risk_state?.reason || '当前没有风控阻断';
      document.getElementById('status-badge').textContent = translateStatus(data.connection_status || 'unknown');
      document.getElementById('status-badge').className = `badge ${pickPillClass(data.risk_state?.status || data.connection_status)}`;
      document.getElementById('board-positive').textContent = String(data.market_board?.stats?.positive_pairs || 0);
      document.getElementById('board-negative').textContent = String(data.market_board?.stats?.negative_pairs || 0);
      document.getElementById('board-average').textContent = asPct(data.market_board?.stats?.average_change_percent || 0);
      document.getElementById('board-tracked').textContent = `跟踪币种：${data.market_board?.stats?.tracked_pairs || 0}`;
      document.getElementById('control-pending').textContent = `控制队列 ${Number(data.control_state?.pending_count || 0)}`;
      const litePlan = (data.trade_plans || [])[0];
      if (litePlan) {
        document.getElementById('hero-action').textContent = `${litePlan.symbol} ${translatePlanStatus(litePlan.status)}`;
        document.getElementById('hero-summary').textContent = `${translateStrategy(litePlan.strategy_name)} / ${litePlan.timeframe}：${litePlan.reason}`;
      }
    }

    function setTransportBanner(message, kind = 'neutral') {
      const target = document.getElementById('transport-banner');
      target.textContent = message;
      if (kind === 'error') {
        target.style.background = 'rgba(163,48,38,0.10)';
        target.style.borderColor = 'rgba(163,48,38,0.18)';
        target.style.color = '#a33026';
      } else if (kind === 'ok') {
        target.style.background = 'rgba(9,91,73,0.08)';
        target.style.borderColor = 'rgba(9,91,73,0.18)';
        target.style.color = '#095b49';
      } else {
        target.style.background = 'rgba(255,255,255,0.72)';
        target.style.borderColor = 'rgba(22,37,34,0.08)';
        target.style.color = '#596461';
      }
    }

    function emptyFilteredState() {
      return {
        filteredSignals: [],
        filteredOrders: [],
        filteredFills: [],
        filteredTimeline: [],
        filteredRisk: [],
        filteredConnections: [],
        filteredPlans: [],
        filteredPriceSeries: [],
        filteredEquity: [],
        priceSeriesKey: null
      };
    }

    function renderPlanCards(data, filtered) {
      const target = document.getElementById('plan-grid');
      const plans = filtered.filteredPlans.length ? filtered.filteredPlans : (data.trade_plans || []);
      if (!plans.length) {
        target.innerHTML = '<div class="plan-card"><div class="plan-title">暂无计划</div><div class="plan-reason">当前还没有形成可执行或可解释的计划卡片。通常是刚启动、K 线预热不够，或者当前筛选窗口下没有匹配数据。</div></div>';
        return;
      }
      target.innerHTML = plans.map(plan => {
        const blockedReasons = (plan.blocked_reasons || []).map(item => escapeHtml(item)).join('；');
        const extraReason = blockedReasons ? ` 风控原因：${blockedReasons}` : '';
        return `
          <div class="plan-card">
            <div class="plan-top">
              <div>
                <div class="plan-title">${escapeHtml(plan.symbol)}</div>
                <div class="plan-sub">${escapeHtml(translateStrategy(plan.strategy_name))} / ${escapeHtml(plan.timeframe)}</div>
              </div>
              <span class="pill ${pickPillClass(plan.status)}">${escapeHtml(translatePlanStatus(plan.status))}</span>
            </div>
            <div class="plan-body">
              <div class="plan-stat">
                <div class="plan-stat-label">当前动作</div>
                <div class="plan-stat-value">${escapeHtml(translateSignal(plan.signal_type))}</div>
              </div>
              <div class="plan-stat">
                <div class="plan-stat-label">参考入场</div>
                <div class="plan-stat-value">${escapeHtml(asMoney(plan.entry_price))}</div>
              </div>
              <div class="plan-stat">
                <div class="plan-stat-label">止损</div>
                <div class="plan-stat-value">${escapeHtml(asMoney(plan.stop_loss))}</div>
              </div>
              <div class="plan-stat">
                <div class="plan-stat-label">止盈</div>
                <div class="plan-stat-value">${escapeHtml(asMoney(plan.take_profit))}</div>
              </div>
              <div class="plan-stat">
                <div class="plan-stat-label">建议数量</div>
                <div class="plan-stat-value">${escapeHtml(asQty(plan.quantity))}</div>
              </div>
              <div class="plan-stat">
                <div class="plan-stat-label">风险预算</div>
                <div class="plan-stat-value">${escapeHtml(asMoney(plan.risk_budget))}</div>
              </div>
              <div class="plan-stat">
                <div class="plan-stat-label">名义价值</div>
                <div class="plan-stat-value">${escapeHtml(asMoney(plan.notional_value))}</div>
              </div>
              <div class="plan-stat">
                <div class="plan-stat-label">预估亏损</div>
                <div class="plan-stat-value">${escapeHtml(asMoney(plan.risk_amount))}</div>
              </div>
              <div class="plan-stat">
                <div class="plan-stat-label">盈亏比</div>
                <div class="plan-stat-value">${escapeHtml(asRatio(plan.risk_reward_ratio))}</div>
              </div>
            </div>
            <div class="plan-reason">${escapeHtml(plan.reason || '无')}${extraReason}</div>
          </div>
        `;
      }).join('');
    }

    function renderControlPanel(data) {
      const strategySelect = document.getElementById('strategy-switch');
      const supported = data.control_state?.supported_strategies || [];
      const options = supported.map(item => `<option value="${escapeHtml(item.internal)}">${escapeHtml(item.public)} / ${escapeHtml(item.description)}</option>`).join('');
      strategySelect.innerHTML = options;
      const current = normalizeStrategy(data.active_strategy);
      if ([...strategySelect.options].some(option => option.value === current)) {
        strategySelect.value = current;
      }

      const pauseBtn = document.getElementById('pause-btn');
      const resumeBtn = document.getElementById('resume-btn');
      const switchBtn = document.getElementById('switch-strategy-btn');
      const riskStatus = String(data.risk_state?.status || '').toLowerCase();
      pauseBtn.disabled = riskStatus === 'paused' || riskStatus === 'protect';
      resumeBtn.disabled = riskStatus === 'active' || riskStatus === 'protect';
      switchBtn.disabled = false;

      const events = data.control_state?.events || [];
      const target = document.getElementById('control-events');
      if (!events.length) {
        target.innerHTML = '<div class="event-item"><strong>还没有控制回执</strong><span>当你点击暂停、恢复或切换策略后，处理结果会显示在这里。</span></div>';
      } else {
        target.innerHTML = events.map(event => `
          <div class="event-item">
            <strong>${escapeHtml(event.success ? '已执行' : '未执行')} / ${escapeHtml(event.action)}</strong>
            <span>${escapeHtml(String(event.timestamp || '').replace('T', ' ').slice(0, 19))}</span>
            <span>${escapeHtml(event.message || '')}</span>
          </div>
        `).join('');
      }
    }

    function renderTables(data, filtered) {
      renderRows('positions-table', [
        { label: '交易对', render: row => escapeHtml(row.symbol) },
        { label: '数量', render: row => `<span class="mono">${escapeHtml(asQty(row.quantity))}</span>` },
        { label: '均价', render: row => escapeHtml(asMoney(row.average_price)) },
        { label: '现价', render: row => escapeHtml(asMoney(row.market_price)) },
        { label: '浮盈亏', render: row => `<span class="${Number(row.unrealized_pnl || 0) < 0 ? 'muted' : ''}">${escapeHtml(asMoney(row.unrealized_pnl))}</span>` }
      ], Object.values(data.positions || {}).filter(row => Number(row.quantity || 0) > 0), '当前没有持仓');

      renderRows('fills-table', [
        { label: '时间', render: row => escapeHtml(String(row.timestamp || '').replace('T', ' ').slice(0, 19)) },
        { label: '交易对', render: row => escapeHtml(row.symbol) },
        { label: '方向', render: row => `<span class="pill ${pickPillClass(row.side)}">${escapeHtml(translateSide(row.side))}</span>` },
        { label: '数量', render: row => `<span class="mono">${escapeHtml(asQty(row.quantity))}</span>` },
        { label: '价格', render: row => escapeHtml(asMoney(row.price)) },
        { label: '已实现盈亏', render: row => escapeHtml(asMoney(row.realized_pnl)) }
      ], filtered.filteredFills.slice(-10).reverse(), '当前筛选窗口内没有成交');

      renderRows('orders-table', [
        { label: '时间', render: row => escapeHtml(String(row.updated_at || '').replace('T', ' ').slice(0, 19)) },
        { label: '交易对', render: row => escapeHtml(row.symbol) },
        { label: '策略', render: row => escapeHtml(translateStrategy(row.metadata?.strategy || '-')) },
        { label: '状态', render: row => `<span class="pill ${pickPillClass(row.status)}">${escapeHtml(translateStatus(row.status))}</span>` },
        { label: '数量', render: row => `<span class="mono">${escapeHtml(asQty(row.quantity))}</span>` },
        { label: '成交均价', render: row => escapeHtml(asMoney(row.average_price)) },
        {
          label: '操作',
          render: row => {
            const canCancel = supportsManualOrders(data.mode) && String(row.status || '').toUpperCase() === 'NEW';
            return canCancel
              ? `<button class="table-action-btn" data-cancel-order="${escapeHtml(row.order_id)}" data-cancel-symbol="${escapeHtml(row.symbol)}">撤单</button>`
              : '<span class="muted">-</span>';
          }
        }
      ], filtered.filteredOrders.slice(-10).reverse(), '当前筛选窗口内没有订单');

      renderRows('signals-table', [
        { label: '时间', render: row => escapeHtml(String(row.timestamp || '').replace('T', ' ').slice(0, 19)) },
        { label: '交易对', render: row => escapeHtml(row.symbol) },
        { label: '策略', render: row => escapeHtml(translateStrategy(row.strategy_name)) },
        { label: '信号', render: row => `<span class="pill ${pickPillClass(row.signal_type)}">${escapeHtml(translateSignal(row.signal_type))}</span>` },
        { label: '原因', render: row => escapeHtml(row.reason) }
      ], filtered.filteredSignals.slice(-10).reverse(), '当前筛选窗口内没有信号');

      renderRows('timeline-table', [
        { label: '时间', render: row => escapeHtml(String(row.timestamp || '').replace('T', ' ').slice(0, 19)) },
        { label: '订单ID', render: row => `<span class="mono">${escapeHtml(row.order_id)}</span>` },
        { label: '策略', render: row => escapeHtml(translateStrategy(row.strategy_name || '-')) },
        { label: '状态', render: row => `<span class="pill ${pickPillClass(row.status)}">${escapeHtml(translateStatus(row.status))}</span>` },
        { label: '说明', render: row => escapeHtml(row.message) }
      ], filtered.filteredTimeline.slice(-10).reverse(), '当前窗口内没有订单时间线数据');

      renderRows('connection-table', [
        { label: '时间', render: row => escapeHtml(String(row.timestamp || '').replace('T', ' ').slice(0, 19)) },
        { label: '通道', render: row => escapeHtml(translateChannel(row.channel)) },
        { label: '状态', render: row => `<span class="pill ${pickPillClass(row.state)}">${escapeHtml(translateStatus(row.state))}</span>` },
        { label: '说明', render: row => escapeHtml(row.message) }
      ], filtered.filteredConnections.slice(-10).reverse(), '当前窗口内没有连接事件');

      renderRows('risk-table', [
        { label: '时间', render: row => escapeHtml(String(row.timestamp || '').replace('T', ' ').slice(0, 19)) },
        { label: '类型', render: row => `<span class="pill ${pickPillClass(row.status)}">${escapeHtml(translateRiskEventType(row.event_type))}</span>` },
        { label: '说明', render: row => escapeHtml(row.message) },
        { label: '交易对', render: row => escapeHtml(row.details?.symbol || '-') }
      ], filtered.filteredRisk.slice(-12).reverse(), '当前筛选窗口内没有风控事件');

      document.querySelectorAll('[data-cancel-order]').forEach(button => {
        button.addEventListener('click', () => {
          sendControl('cancel_order', {
            order_id: button.getAttribute('data-cancel-order'),
            symbol: button.getAttribute('data-cancel-symbol')
          });
        });
      });
    }

    function updateCharts(filtered) {
      drawLineChart('equity-chart', filtered.filteredEquity, row => Number(row.net_asset_value || 0), '#095b49', 'rgba(9,91,73,0.13)');
      drawLineChart('pnl-chart', filtered.filteredEquity, row => Number(row.session_pnl || 0), '#d46a26', 'rgba(212,106,38,0.16)');
      drawPriceChart('price-chart', filtered.filteredPriceSeries);
    }

    function showToast(message) {
      const toast = document.getElementById('toast');
      toast.textContent = message;
      toast.classList.add('show');
      window.clearTimeout(showToast._timer);
      showToast._timer = window.setTimeout(() => toast.classList.remove('show'), 2600);
    }

    async function sendControl(action, params = {}) {
      try {
        const response = await fetch('/api/control', {
          method: 'POST',
          cache: 'no-store',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action, params })
        });
        const payload = await response.json();
        if (!response.ok) {
          showToast(payload.message || '控制指令发送失败');
          return;
        }
        showToast(payload.message || '控制指令已发送');
        await refresh();
      } catch (error) {
        showToast(`控制指令发送失败：${error}`);
      }
    }

    async function requestSymbolAnalysis(symbol, timeframe = null, strategy = null) {
      const targetTimeframe = timeframe || document.getElementById('manual-timeframe').value || latestData?.tracked_timeframes?.[0] || '1m';
      try {
        const response = await fetch('/api/analyze-symbol', {
          method: 'POST',
          cache: 'no-store',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            symbol,
            timeframe: targetTimeframe,
            strategy: strategy || document.getElementById('strategy-switch').value || latestData?.active_strategy
          })
        });
        const payload = await response.json();
        if (!response.ok || payload.ok === false) {
          showToast(payload.message || '实时分析失败');
          return;
        }
        selectedAnalysis = payload;
        const normalized = normalizeSymbol(payload.symbol);
        if ([...document.getElementById('symbol-filter').options].some(option => option.value === normalized)) {
          document.getElementById('symbol-filter').value = normalized;
          filters.symbol = normalized;
        }
        if ([...document.getElementById('timeframe-filter').options].some(option => option.value === payload.timeframe)) {
          document.getElementById('timeframe-filter').value = payload.timeframe;
          filters.timeframe = payload.timeframe;
        }
        renderAnalysisCard();
        showToast(`${displaySymbol(payload.symbol)} 的实时分析已更新`);
      } catch (error) {
        showToast(`实时分析失败：${error}`);
      }
    }

    function attachControlListeners() {
      document.getElementById('pause-btn').addEventListener('click', () => sendControl('pause', { reason: '来自网页控制台的手动暂停' }));
      document.getElementById('resume-btn').addEventListener('click', () => sendControl('resume', {}));
      document.getElementById('switch-strategy-btn').addEventListener('click', () => {
        const strategy = document.getElementById('strategy-switch').value;
        sendControl('switch_strategy', { strategy });
      });
    }

    function attachManualListeners() {
      document.getElementById('fill-from-analysis-btn').addEventListener('click', () => applyAnalysisToManualForm());
      document.getElementById('manual-order-btn').addEventListener('click', () => {
        if (!supportsManualOrders(latestData?.mode)) {
          showToast('当前模式不允许网页手动下单');
          return;
        }
        const params = {
          symbol: document.getElementById('manual-symbol').value,
          timeframe: document.getElementById('manual-timeframe').value,
          side: document.getElementById('manual-side').value,
          order_type: document.getElementById('manual-order-type').value,
          quantity: document.getElementById('manual-quantity').value,
          price: document.getElementById('manual-price').value,
          strategy: document.getElementById('strategy-switch').value || latestData?.active_strategy
        };
        sendControl('manual_order', params);
      });
      document.getElementById('manual-order-type').addEventListener('change', event => {
        const isLimit = event.target.value === 'LIMIT';
        document.getElementById('manual-price').disabled = !isLimit;
        if (!isLimit) document.getElementById('manual-price').value = '';
      });
    }

    function attachFilterListeners() {
      ['symbol-filter', 'strategy-filter', 'timeframe-filter', 'window-filter'].forEach(id => {
        document.getElementById(id).addEventListener('change', event => {
          const key = id.replace('-filter', '');
          filters[key] = event.target.value;
          if (latestData) renderPage(latestData, false);
        });
      });
      document.getElementById('market-board-search').addEventListener('input', () => {
        if (latestData) renderMarketBoard(latestData);
      });
      document.getElementById('market-board-mode').addEventListener('change', event => {
        selectedBoardMode = event.target.value || 'gainers';
        if (latestData) {
          renderBootStatus(latestData);
          renderMarketPulse(latestData);
          renderMarketBoard(latestData);
        }
      });
    }

    function renderPage(data, syncOptions = true) {
      latestData = data;
      rememberSync('full', data);
      guardRender('启动状态', () => renderBootStatus(data));
      guardRender('轻量概览', () => renderLiteSummary(data));
      if (syncOptions) guardRender('筛选器同步', () => syncFilterControls(data));
      guardRender('手动下单面板', () => syncManualControls(data));
      filters.symbol = document.getElementById('symbol-filter').value || 'ALL';
      filters.strategy = document.getElementById('strategy-filter').value || 'ALL';
      filters.timeframe = document.getElementById('timeframe-filter').value || 'ALL';
      filters.window = document.getElementById('window-filter').value || '60';

      const filtered = guardRender('数据过滤', () => applyDataFilters(data), emptyFilteredState());
      guardRender('市场脉搏', () => renderMarketPulse(data));
      guardRender('完整概览', () => updateSummary(data, filtered));
      guardRender('控制面板', () => renderControlPanel(data));
      guardRender('网络诊断', () => renderNetworkDiagnostics(data));
      guardRender('榜单表格', () => renderMarketBoard(data));
      guardRender('实时分析卡', () => renderAnalysisCard());
      guardRender('计划卡', () => renderPlanCards(data, filtered));
      guardRender('图表区', () => updateCharts(filtered));
      guardRender('明细表格', () => renderTables(data, filtered));
      const payloadBytes = Number(data.payload_meta?.payload_bytes || 0);
      const hiddenPositions = Number(data.position_stats?.hidden_count || 0);
      setTransportBanner(
        `页面与本地服务已连通。当前模式：${translateMode(data.mode)}，连接状态：${translateStatus(data.connection_status)}，榜单 ${data.market_board?.rows?.length || 0} 个，状态包 ${(payloadBytes / 1024).toFixed(1)} KB${hiddenPositions > 0 ? `，已对 ${hiddenPositions} 个较小持仓做轻量化显示` : ''}。`,
        'ok'
      );
    }

    function renderLiteSnapshot(data) {
      rememberSync('lite', data);
      guardRender('轻量启动状态', () => renderBootStatus(data));
      guardRender('轻量概览卡', () => renderLiteSummary(data));
      guardRender('轻量市场脉搏', () => renderMarketPulse(data));
      const rowCount = Number(data.market_board?.row_count || data.market_board?.stats?.visible_pairs || 0);
      setTransportBanner(
        `轻量状态已同步。当前模式：${translateMode(data.mode)}，连接状态：${translateStatus(data.connection_status)}，轻量榜单 ${rowCount} 个，等待完整数据继续补齐。`,
        rowCount > 0 ? 'ok' : 'neutral'
      );
    }

    async function refreshFull(force = false) {
      if (fullRefreshInFlight && !force) return;
      fullRefreshInFlight = true;
      try {
        const response = await fetch(`/api/status?ts=${Date.now()}`, { cache: 'no-store' });
        if (!response.ok) {
          throw new Error(`状态接口返回 ${response.status}`);
        }
        const data = await response.json();
        refreshFailures = 0;
        renderPage(data, true);
      } catch (error) {
        refreshFailures += 1;
        reportClientError(`完整刷新第 ${refreshFailures} 次`, error);
      } finally {
        fullRefreshInFlight = false;
      }
    }

    async function refreshLite() {
      if (liteRefreshInFlight) return;
      liteRefreshInFlight = true;
      try {
        const response = await fetch(`/api/status-lite?ts=${Date.now()}`, { cache: 'no-store' });
        if (!response.ok) {
          throw new Error(`轻量状态接口返回 ${response.status}`);
        }
        const data = await response.json();
        renderLiteSnapshot(data);
        if (!latestData || Number(data.snapshot_revision || 0) !== lastFullRevision) {
          await refreshFull(true);
        }
      } catch (error) {
        refreshFailures += 1;
        reportClientError(`轻量刷新第 ${refreshFailures} 次`, error);
      } finally {
        liteRefreshInFlight = false;
      }
    }

    window.addEventListener('error', event => {
      reportClientError('前端脚本', event.error || event.message);
    });
    window.addEventListener('unhandledrejection', event => {
      reportClientError('异步任务', event.reason);
    });

    attachControlListeners();
    attachManualListeners();
    attachFilterListeners();
    updateHeartbeat();
    refreshLite();
    refreshFull();
    setInterval(updateHeartbeat, 1000);
    setInterval(refreshLite, 1000);
    setInterval(() => {
      if (!fullRefreshInFlight) refreshFull();
    }, 4000);
  </script>
</body>
</html>
"""


class WebDashboard:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8765,
        start_server: bool = True,
        control_plane: ControlPlane | None = None,
        auto_open_browser: bool = False,
        browser_url: str | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.control_plane = control_plane or ControlPlane()
        self.auto_open_browser = auto_open_browser
        self.browser_url = browser_url or f"http://{self.host}:{self.port}/?launch={int(time.time())}"
        self._analyze_handler = None
        self._snapshot: dict = {
            "ui_version": UI_VERSION,
            "snapshot_revision": 0,
            "mode": "unknown",
            "connection_status": "starting",
            "active_strategy": "",
            "tracked_symbols": [],
            "tracked_timeframes": [],
            "market_board": {"updated_at": None, "source": "starting", "rows": []},
            "network_diagnostics": {"updated_at": None, "summary": "等待网络诊断", "recommendations": []},
            "trade_plans": [],
            "control_state": self.control_plane.describe(),
            "account": None,
            "positions": {},
            "position_stats": {"open_count": 0, "displayed_count": 0, "hidden_count": 0},
            "recent_signals": [],
            "recent_orders": [],
            "recent_fills": [],
            "order_timeline": [],
            "connection_events": [],
            "price_history": {},
            "equity_history": [],
            "risk_events": [],
            "risk_state": {},
            "payload_meta": {"payload_bytes": 0, "trimmed": False},
        }
        self._snapshot_revision = 0
        self._lite_snapshot: dict = self._build_lite_payload(self._snapshot)
        self._lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        if start_server:
            self._server = ThreadingHTTPServer((host, port), self._build_handler())
            self.port = self._server.server_address[1]
            self.browser_url = browser_url or f"http://{self.host}:{self.port}/?launch={int(time.time())}"
            self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            self._thread.start()
            if self.auto_open_browser:
                threading.Thread(target=self._open_browser_when_ready, daemon=True).start()

    def _open_browser_when_ready(self) -> None:
        health_url = f"http://{self.host}:{self.port}/health"
        deadline = time.time() + 15.0
        while time.time() < deadline:
            try:
                with urlopen(health_url, timeout=1.0) as response:
                    if response.status == 200:
                        break
            except Exception:
                time.sleep(0.5)
                continue
        target_url = self.browser_url or f"http://{self.host}:{self.port}/?launch={int(time.time())}"
        try:
            if webbrowser.open_new_tab(target_url):
                return
        except Exception:
            pass
        for command in (
            ["open", target_url],
            ["open", "-a", "Safari", target_url],
        ):
            try:
                subprocess.run(command, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except Exception:
                continue

    def _build_handler(self) -> type[BaseHTTPRequestHandler]:
        parent = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                request_path = self.path.split("?", 1)[0]
                if request_path == "/":
                    self._respond(HTTPStatus.OK, "text/html; charset=utf-8", HTML_PAGE.encode("utf-8"))
                    return
                if request_path == "/api/status":
                    with parent._lock:
                        payload = json.dumps(parent._snapshot, ensure_ascii=True).encode("utf-8")
                    self._respond(HTTPStatus.OK, "application/json; charset=utf-8", payload)
                    return
                if request_path == "/api/status-lite":
                    with parent._lock:
                        payload = json.dumps(parent._lite_snapshot, ensure_ascii=True).encode("utf-8")
                    self._respond(HTTPStatus.OK, "application/json; charset=utf-8", payload)
                    return
                if request_path == "/health":
                    self._respond(HTTPStatus.OK, "text/plain; charset=utf-8", b"ok")
                    return
                self._respond(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", "未找到".encode("utf-8"))

            def do_POST(self) -> None:  # noqa: N802
                request_path = self.path.split("?", 1)[0]
                if request_path == "/api/analyze-symbol":
                    length = int(self.headers.get("Content-Length", "0") or "0")
                    try:
                        payload = json.loads(self.rfile.read(length).decode("utf-8") if length else "{}")
                    except json.JSONDecodeError:
                        self._respond_json(
                            HTTPStatus.BAD_REQUEST,
                            {"ok": False, "message": "分析请求不是合法的 JSON。"},
                        )
                        return
                    if parent._analyze_handler is None:
                        self._respond_json(
                            HTTPStatus.SERVICE_UNAVAILABLE,
                            {"ok": False, "message": "分析服务尚未就绪，请稍后再试。"},
                        )
                        return
                    symbol = str(payload.get("symbol") or "").strip()
                    timeframe = str(payload.get("timeframe") or "1m").strip() or "1m"
                    strategy = payload.get("strategy")
                    if not symbol:
                        self._respond_json(
                            HTTPStatus.BAD_REQUEST,
                            {"ok": False, "message": "分析请求缺少交易对。"},
                        )
                        return
                    try:
                        result = parent._analyze_handler(symbol, timeframe, strategy)
                    except Exception as exc:  # pragma: no cover - runtime callback
                        self._respond_json(
                            HTTPStatus.INTERNAL_SERVER_ERROR,
                            {"ok": False, "message": f"实时分析失败：{exc}"},
                        )
                        return
                    self._respond_json(HTTPStatus.OK, result)
                    return
                if request_path != "/api/control":
                    self._respond(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", "未找到".encode("utf-8"))
                    return
                length = int(self.headers.get("Content-Length", "0") or "0")
                try:
                    payload = json.loads(self.rfile.read(length).decode("utf-8") if length else "{}")
                except json.JSONDecodeError:
                    self._respond_json(
                        HTTPStatus.BAD_REQUEST,
                        {"accepted": False, "message": "控制指令不是合法的 JSON。"},
                    )
                    return
                action = str(payload.get("action") or "").strip()
                params = payload.get("params") or {}
                if not action:
                    self._respond_json(
                        HTTPStatus.BAD_REQUEST,
                        {"accepted": False, "message": "缺少控制动作。"},
                    )
                    return
                result = parent.control_plane.submit(action, params)
                self._respond_json(HTTPStatus.OK, result)

            def log_message(self, format: str, *args) -> None:  # noqa: A003
                return

            def _respond(self, status: HTTPStatus, content_type: str, body: bytes) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                self.end_headers()
                self.wfile.write(body)

            def _respond_json(self, status: HTTPStatus, payload: dict) -> None:
                self._respond(
                    status,
                    "application/json; charset=utf-8",
                    json.dumps(payload, ensure_ascii=True).encode("utf-8"),
                )

        return Handler

    def _compact_account(self, account: dict[str, Any] | None) -> dict[str, Any] | None:
        if not account:
            return None
        balances = account.get("balances") or {}
        preview_rows = []
        for asset, row in balances.items():
            free = float(row.get("free", 0.0) or 0.0)
            locked = float(row.get("locked", 0.0) or 0.0)
            total = free + locked
            if total <= 0:
                continue
            preview_rows.append(
                {
                    "asset": asset,
                    "free": free,
                    "locked": locked,
                    "total": total,
                }
            )
        preview_rows.sort(key=lambda item: item["total"], reverse=True)
        return {
            "timestamp": account.get("timestamp"),
            "net_asset_value": account.get("net_asset_value"),
            "available_quote_balance": account.get("available_quote_balance"),
            "balance_count": len(balances),
            "non_zero_balance_count": len(preview_rows),
            "balance_preview": preview_rows[:WEB_MAX_BALANCE_PREVIEW],
        }

    def _compact_positions(
        self,
        positions: dict[str, Any],
        tracked_symbols: list[str],
        trade_plans: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], dict[str, int]]:
        tracked = {str(symbol).replace("/", "").upper() for symbol in tracked_symbols}
        tracked.update(str(plan.get("symbol", "")).replace("/", "").upper() for plan in trade_plans)
        open_rows: list[dict[str, Any]] = []
        for symbol, row in positions.items():
            quantity = float(row.get("quantity", 0.0) or 0.0)
            market_price = float(row.get("market_price", 0.0) or 0.0)
            average_price = float(row.get("average_price", 0.0) or 0.0)
            notional = abs(quantity) * (market_price or average_price)
            if quantity <= 0 and str(symbol).upper() not in tracked:
                continue
            entry = dict(row)
            entry["display_notional"] = notional
            open_rows.append(entry)
        open_rows.sort(
            key=lambda item: (
                float(item.get("display_notional", 0.0) or 0.0),
                float(item.get("unrealized_pnl", 0.0) or 0.0),
            ),
            reverse=True,
        )
        visible_rows = open_rows[:WEB_MAX_POSITIONS]
        compact_positions = {str(row.get("symbol") or ""): row for row in visible_rows if row.get("symbol")}
        return compact_positions, {
            "open_count": len(open_rows),
            "displayed_count": len(visible_rows),
            "hidden_count": max(0, len(open_rows) - len(visible_rows)),
        }

    def _compact_market_board(self, board: dict[str, Any]) -> dict[str, Any]:
        sections = board.get("sections") or {}
        compact_sections = {
            name: list(rows[:WEB_MAX_MARKET_ROWS]) for name, rows in sections.items()
        }
        compact_rows = list((board.get("rows") or [])[:WEB_MAX_MARKET_ROWS])
        stats = dict(board.get("stats") or {})
        stats["visible_pairs"] = len(compact_rows)
        return {
            "updated_at": board.get("updated_at"),
            "source": board.get("source"),
            "message": board.get("message"),
            "stats": stats,
            "rows": compact_rows,
            "sections": compact_sections,
        }

    def _compact_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        compact = dict(payload)
        compact["account"] = self._compact_account(payload.get("account"))
        compact_positions, position_stats = self._compact_positions(
            payload.get("positions") or {},
            payload.get("tracked_symbols") or [],
            payload.get("trade_plans") or [],
        )
        compact["positions"] = compact_positions
        compact["position_stats"] = position_stats
        compact["market_board"] = self._compact_market_board(payload.get("market_board") or {})
        compact["price_history"] = {
            key: list(series[-WEB_MAX_PRICE_POINTS:])
            for key, series in (payload.get("price_history") or {}).items()
        }
        compact["equity_history"] = list((payload.get("equity_history") or [])[-WEB_MAX_EQUITY_POINTS:])
        for key in (
            "trade_plans",
            "recent_signals",
            "recent_orders",
            "recent_fills",
            "order_timeline",
            "connection_events",
            "risk_events",
        ):
            compact[key] = list((payload.get(key) or [])[-WEB_MAX_RECENT_ROWS:])
        compact["payload_meta"] = {
            "trimmed": True,
            "payload_bytes": 0,
            "visible_positions": position_stats["displayed_count"],
            "hidden_positions": position_stats["hidden_count"],
            "visible_board_rows": len(compact["market_board"].get("rows") or []),
        }
        compact["payload_meta"]["payload_bytes"] = len(json.dumps(compact, ensure_ascii=True))
        return compact

    def _build_lite_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        board = payload.get("market_board") or {}
        sections = board.get("sections") or {}
        diagnostics = payload.get("network_diagnostics") or {}
        control_state = payload.get("control_state") or {}
        return {
            "ui_version": payload.get("ui_version", UI_VERSION),
            "snapshot_revision": payload.get("snapshot_revision", 0),
            "mode": payload.get("mode", "unknown"),
            "connection_status": payload.get("connection_status", "starting"),
            "active_strategy": payload.get("active_strategy", ""),
            "tracked_symbols": list((payload.get("tracked_symbols") or [])[:12]),
            "tracked_timeframes": list((payload.get("tracked_timeframes") or [])[:6]),
            "account": payload.get("account"),
            "risk_state": payload.get("risk_state") or {},
            "market_board": {
                "updated_at": board.get("updated_at"),
                "source": board.get("source"),
                "message": board.get("message"),
                "stats": dict(board.get("stats") or {}),
                "row_count": len(board.get("rows") or []),
                "sections": {
                    name: list(rows[:8]) for name, rows in sections.items()
                },
            },
            "trade_plans": list((payload.get("trade_plans") or [])[:4]),
            "recent_signals": list((payload.get("recent_signals") or [])[:4]),
            "position_stats": dict(payload.get("position_stats") or {}),
            "payload_meta": dict(payload.get("payload_meta") or {}),
            "control_state": {
                "pending_count": control_state.get("pending_count", 0),
                "supported_strategies": list((control_state.get("supported_strategies") or [])[:8]),
            },
            "network_diagnostics": {
                "updated_at": diagnostics.get("updated_at"),
                "summary": diagnostics.get("summary"),
                "shadowrocket": diagnostics.get("shadowrocket"),
                "dns": diagnostics.get("dns"),
                "endpoints": [
                    {
                        "name": endpoint.get("name"),
                        "status": endpoint.get("status"),
                        "http_status": endpoint.get("http_status"),
                        "message": endpoint.get("message"),
                    }
                    for endpoint in list((diagnostics.get("endpoints") or [])[:6])
                ],
                "recommendations": list((diagnostics.get("recommendations") or [])[:4]),
            },
            "client_hints": {
                "lite_poll_ms": 1000,
                "full_poll_ms": 4000,
            },
        }

    def render(self, snapshot: RuntimeSnapshot) -> None:
        with self._lock:
            payload = runtime_snapshot_to_dict(snapshot)
            payload["ui_version"] = UI_VERSION
            payload["control_state"] = self.control_plane.describe()
            self._snapshot_revision += 1
            payload["snapshot_revision"] = self._snapshot_revision
            self._snapshot = self._compact_payload(payload)
            self._lite_snapshot = self._build_lite_payload(self._snapshot)

    def set_analyze_handler(self, handler) -> None:
        self._analyze_handler = handler

    def current_payload(self) -> dict:
        with self._lock:
            return json.loads(json.dumps(self._snapshot, ensure_ascii=True))

    def current_lite_payload(self) -> dict:
        with self._lock:
            return json.loads(json.dumps(self._lite_snapshot, ensure_ascii=True))

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
        if self._thread:
            self._thread.join(timeout=2)


class CompositeDashboard:
    def __init__(self, dashboards: list[object]) -> None:
        self.dashboards = dashboards

    def render(self, snapshot: RuntimeSnapshot) -> None:
        for dashboard in self.dashboards:
            dashboard.render(snapshot)

    def stop(self) -> None:
        for dashboard in self.dashboards:
            stop = getattr(dashboard, "stop", None)
            if callable(stop):
                stop()
