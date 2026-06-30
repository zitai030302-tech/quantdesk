from __future__ import annotations

import asyncio
import ipaddress
import plistlib
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from data.models import utc_now


class BinanceNetworkDiagnosticsService:
    def __init__(
        self,
        refresh_interval_sec: float = 60.0,
        shadowrocket_group_dir: str | None = None,
    ) -> None:
        self.refresh_interval = timedelta(seconds=refresh_interval_sec)
        self.shadowrocket_group_dir = (
            Path(shadowrocket_group_dir)
            if shadowrocket_group_dir
            else Path.home() / "Library" / "Group Containers" / "group.com.liguangming.Shadowrocket"
        )
        self._snapshot: dict[str, Any] = {
            "updated_at": None,
            "proxy": {},
            "dns": {},
            "shadowrocket": {},
            "endpoints": [],
            "summary": "等待网络诊断",
            "recommendations": [],
            "rule_snippets": [],
        }
        self._updated_at: datetime | None = None

    async def refresh(self, force: bool = False) -> dict[str, Any]:
        if not force and self._updated_at and utc_now() - self._updated_at < self.refresh_interval:
            return self.snapshot()

        proxy_info, dns_info, shadowrocket_info = await asyncio.gather(
            asyncio.to_thread(self._read_proxy_info),
            asyncio.to_thread(self._read_dns_info),
            asyncio.to_thread(self._read_shadowrocket_info),
        )
        resolved_hosts = await asyncio.to_thread(self._resolve_hosts)
        endpoints = await self._check_endpoints()
        snapshot = self._build_snapshot(
            proxy_info=proxy_info,
            dns_info=dns_info,
            shadowrocket_info=shadowrocket_info,
            resolved_hosts=resolved_hosts,
            endpoints=endpoints,
        )
        self._snapshot = snapshot
        self._updated_at = utc_now()
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        return dict(self._snapshot)

    def _build_snapshot(
        self,
        proxy_info: dict[str, Any],
        dns_info: dict[str, Any],
        shadowrocket_info: dict[str, Any],
        resolved_hosts: list[dict[str, Any]],
        endpoints: list[dict[str, Any]],
    ) -> dict[str, Any]:
        selected_server = str(shadowrocket_info.get("selected_server") or "")
        selected_server_upper = selected_server.upper()
        using_us_exit = any(token in selected_server for token in ("美国",)) or any(
            token in selected_server_upper for token in ("US", "USA", "UNITED STATES")
        )
        fake_ip_detected = any(row.get("is_fake_ip") for row in resolved_hosts)
        blocked_targets = [row["name"] for row in endpoints if row.get("status") == "blocked"]
        reachable_targets = [row["name"] for row in endpoints if row.get("status") == "ok"]

        recommendations: list[str] = []
        if using_us_exit:
            recommendations.append("Shadowrocket 当前节点是美国出口。请先切换到香港、新加坡、日本等非美国节点，再重试 Binance 主站和 Testnet。")
        if fake_ip_detected:
            recommendations.append("当前 Binance 相关域名被解析成 198.18.x.x 的 Fake-IP。请在 Shadowrocket 的 DNS / 增强模式里，把 *.binance.com 和 *.binance.vision 改为 redir-host 或关闭这些域名的 Fake-IP。")
        if any(row.get("name") == "Binance 主站 REST" and row.get("http_status") == 451 for row in endpoints):
            recommendations.append("Binance 主站 REST 返回 451，说明当前出口地区不适合访问 Binance Global。请为 binance.com / binance.vision 单独指定非美国节点。")
        if any(row.get("name") == "Binance Testnet REST" and row.get("http_status") == 451 for row in endpoints):
            recommendations.append("Binance Testnet 也返回 451，说明测试盘同样受当前节点地区影响。切换到非美国节点后，再试 testnet.binance.vision 和 ws-api.testnet.binance.vision。")
        if not recommendations:
            recommendations.append("当前网络诊断没有发现明显阻断，可以继续尝试连接 Testnet。")

        if using_us_exit and fake_ip_detected:
            summary = "当前很像是“美国代理节点 + Fake-IP DNS”双重影响，所以 Binance 主站与 Testnet 很容易返回 451。先换成非美国节点，再处理 binance 域名的 Fake-IP。"
        elif using_us_exit:
            summary = "当前代理出口是美国，这会让 Binance Global / Testnet 很容易被地理限制拦住。优先切到非美国节点。"
        elif fake_ip_detected and blocked_targets:
            summary = "当前 DNS 仍在给 Binance 域名分配 Fake-IP，且主站/Testnet 有阻断。建议先把这些域名从 Fake-IP 排除。"
        elif blocked_targets:
            summary = f"当前仍有目标不可达：{'、'.join(blocked_targets)}。"
        elif reachable_targets:
            summary = f"当前网络至少已能访问：{'、'.join(reachable_targets)}。"
        else:
            summary = "网络诊断尚未拿到完整结果。"

        return {
            "updated_at": utc_now().isoformat(),
            "proxy": proxy_info,
            "dns": {
                **dns_info,
                "resolved_hosts": resolved_hosts,
                "fake_ip_detected": fake_ip_detected,
            },
            "shadowrocket": shadowrocket_info,
            "endpoints": endpoints,
            "summary": summary,
            "recommendations": recommendations,
            "rule_snippets": [
                "DOMAIN-SUFFIX,binance.com,非美国节点",
                "DOMAIN-SUFFIX,binance.vision,非美国节点",
                "DOMAIN,api.binance.com,非美国节点",
                "DOMAIN,testnet.binance.vision,非美国节点",
                "DOMAIN,ws-api.testnet.binance.vision,非美国节点",
            ],
        }

    async def _check_endpoints(self) -> list[dict[str, Any]]:
        targets = [
            ("Binance 主站 REST", "https://api.binance.com/api/v3/time"),
            ("Binance Testnet REST", "https://testnet.binance.vision/api/v3/time"),
            ("Binance 行情只读 REST", "https://data-api.binance.vision/api/v3/time"),
        ]
        results = await asyncio.gather(*(self._check_endpoint(name, url) for name, url in targets))
        return list(results)

    async def _check_endpoint(self, name: str, url: str) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=6.0, follow_redirects=True) as client:
                response = await client.get(url)
            status = "ok" if response.status_code < 400 else ("blocked" if response.status_code == 451 else "warning")
            return {
                "name": name,
                "url": url,
                "status": status,
                "http_status": response.status_code,
            }
        except Exception as exc:
            return {
                "name": name,
                "url": url,
                "status": "error",
                "http_status": None,
                "message": str(exc),
            }

    def _read_proxy_info(self) -> dict[str, Any]:
        output = self._run_command(["scutil", "--proxy"])
        return {
            "http_enabled": self._extract_numeric_flag(output, "HTTPEnable"),
            "https_enabled": self._extract_numeric_flag(output, "HTTPSEnable"),
            "http_proxy": self._extract_string_value(output, "HTTPProxy"),
            "http_port": self._extract_string_value(output, "HTTPPort"),
            "https_proxy": self._extract_string_value(output, "HTTPSProxy"),
            "https_port": self._extract_string_value(output, "HTTPSPort"),
        }

    def _read_dns_info(self) -> dict[str, Any]:
        output = self._run_command(["scutil", "--dns"])
        nameservers = re.findall(r"nameserver\[\d+\] : ([^\n]+)", output)
        primary = nameservers[0].strip() if nameservers else ""
        return {
            "primary_nameserver": primary,
            "nameservers": [value.strip() for value in nameservers[:6]],
        }

    def _read_shadowrocket_info(self) -> dict[str, Any]:
        prefs_path = self.shadowrocket_group_dir / "Library" / "Preferences" / "group.com.liguangming.Shadowrocket.plist"
        dns_path = self.shadowrocket_group_dir / "dns.conf"
        info = {
            "selected_server": "",
            "routing_method": "",
            "dns_servers": [],
        }
        if prefs_path.exists():
            with prefs_path.open("rb") as handle:
                prefs = plistlib.load(handle)
            info["selected_server"] = str(prefs.get("group.com.liguangming.SelectedServerName") or "")
            info["routing_method"] = str(prefs.get("group.com.liguangming.GlobalRoutingMethod") or "")
        if dns_path.exists():
            with dns_path.open("rb") as handle:
                dns_servers = plistlib.load(handle)
            if isinstance(dns_servers, list):
                info["dns_servers"] = [str(item) for item in dns_servers]
        return info

    def _resolve_hosts(self) -> list[dict[str, Any]]:
        hosts = [
            "api.binance.com",
            "testnet.binance.vision",
            "ws-api.testnet.binance.vision",
            "data-api.binance.vision",
        ]
        resolved: list[dict[str, Any]] = []
        for host in hosts:
            output = self._run_command(["dscacheutil", "-q", "host", "-a", "name", host])
            ip = self._extract_ip(output)
            resolved.append(
                {
                    "host": host,
                    "ip": ip,
                    "is_fake_ip": self._is_fake_ip(ip),
                }
            )
        return resolved

    @staticmethod
    def _run_command(command: list[str]) -> str:
        try:
            result = subprocess.run(command, capture_output=True, text=True, check=False)
            return result.stdout
        except Exception:
            return ""

    @staticmethod
    def _extract_numeric_flag(text: str, key: str) -> bool:
        match = re.search(rf"{re.escape(key)}\s*:\s*(\d+)", text)
        return bool(match and match.group(1) == "1")

    @staticmethod
    def _extract_string_value(text: str, key: str) -> str:
        match = re.search(rf"{re.escape(key)}\s*:\s*([^\n]+)", text)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _extract_ip(text: str) -> str:
        for pattern in (r"ip_address:\s*([^\n]+)", r"ipv6_address:\s*::ffff:([^\n]+)"):
            match = re.search(pattern, text)
            if match:
                return match.group(1).strip()
        return ""

    @staticmethod
    def _is_fake_ip(ip: str) -> bool:
        if not ip:
            return False
        try:
            address = ipaddress.ip_address(ip)
        except ValueError:
            return False
        return ipaddress.ip_address("198.18.0.0") <= address <= ipaddress.ip_address("198.19.255.255")
