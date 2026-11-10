#!/usr/bin/env python3
"""
Load Testing Script for Smart Document Chatbot
Simulates concurrent users to test system performance.

Usage:
    python scripts/load_test.py --users 100 --duration 60
    python scripts/load_test.py --users 50 --duration 30 --ramp-up 10
"""

import argparse
import asyncio
import json
import statistics
import time
from dataclasses import dataclass
from datetime import datetime

import aiohttp

BASE_URL = "http://localhost:8080/api"


@dataclass(frozen=True)
class VirtualUser:
    user_id: int
    token: str
    csrf: str
    cookies: dict[str, str]
    doc_id: str
    source_ip: str


class LoadTest:
    def __init__(self, num_users: int, duration: int, ramp_up: int = 0, think_time: float = 2.5):
        self.num_users = num_users
        self.duration = duration
        self.ramp_up = ramp_up
        self.think_time = think_time
        self.results = []
        self.errors = []
        self.users: list[VirtualUser] = []

    async def setup(self):
        """Create isolated users so the load test measures concurrent customers."""
        self.users = list(await asyncio.gather(
            *(self.setup_user(user_id) for user_id in range(1, self.num_users + 1))
        ))
        print(f"Setup complete: {len(self.users)} isolated users with separate documents")

    async def setup_user(self, user_id: int) -> VirtualUser:
        """Register/login one virtual user and upload that user's test document."""
        source_ip = f"127.0.0.{(user_id % 254) + 1}"
        connector = aiohttp.TCPConnector(local_addr=(source_ip, 0))
        async with aiohttp.ClientSession(connector=connector) as session:
            # Get CSRF
            async with session.get(f"{BASE_URL}/csrf") as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(f"CSRF fetch failed ({resp.status}): {text}")
                data = await resp.json()
                csrf = data["token"]
                cookies = {
                    name: morsel.value
                    for name, morsel in session.cookie_jar.filter_cookies(BASE_URL).items()
                }

            user_payload = {
                "username": f"loadtest-{user_id}",
                "password": "TestPass123!",
                "email": f"loadtest-{user_id}@example.com",
            }
            async with session.post(
                f"{BASE_URL}/auth/register",
                json=user_payload,
                headers={"X-XSRF-TOKEN": csrf},
            ) as resp:
                token = None
                if resp.status == 200:
                    token = (await resp.json()).get("token")

            if not token:
                async with session.post(
                    f"{BASE_URL}/auth/login",
                    json={"username": user_payload["username"], "password": user_payload["password"]},
                    headers={"X-XSRF-TOKEN": csrf},
                ) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        raise RuntimeError(
                            f"Virtual user {user_id} login failed (HTTP {resp.status}): {text}"
                        )
                    data = await resp.json()
                    token = data.get("token")

            if not token:
                raise RuntimeError(f"Failed to obtain JWT token for virtual user {user_id}")

            doc_content = "LUẬT DOANH NGHIỆP 2020. Điều 7: Hình thức doanh nghiệp. Điều 10: Thủ tục thành lập."
            data = aiohttp.FormData()
            data.add_field("file", doc_content.encode(), filename="load_test.txt", content_type="text/plain")

            async with session.post(
                f"{BASE_URL}/documents/upload",
                data=data,
                headers={"Authorization": f"Bearer {token}", "X-XSRF-TOKEN": csrf},
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(
                        f"Virtual user {user_id} document upload failed "
                        f"(HTTP {resp.status}): {text}"
                    )
                doc_id = (await resp.json()).get("documentId")
                if not doc_id:
                    raise RuntimeError(f"Virtual user {user_id} upload returned no document ID")

        return VirtualUser(user_id, token, csrf, cookies, doc_id, source_ip)

    async def user_session(self, user: VirtualUser):
        """Simulate a single user session."""
        await asyncio.sleep((self.ramp_up / self.num_users) * (user.user_id - 1))
        
        session_start = time.time()
        session_results = []
        
        connector = aiohttp.TCPConnector(local_addr=(user.source_ip, 0))
        async with aiohttp.ClientSession(cookies=user.cookies, connector=connector) as session:
            headers = {
                "Authorization": f"Bearer {user.token}",
                "X-XSRF-TOKEN": user.csrf,
                "Content-Type": "application/json"
            }
            
            questions = [
                "Điều 7 quy định gì?",
                "Điều 10 quy định gì?",
                "Công ty cổ phần là gì?",
                "Quyền của cổ đông?",
                "Nghĩa vụ doanh nghiệp?",
            ]
            
            end_time = session_start + self.duration
            q_idx = 0
            
            while time.time() < end_time:
                q = questions[q_idx % len(questions)]
                q_idx += 1
                
                start = time.time()
                try:
                    async with session.post(f"{BASE_URL}/chat/ask",
                            json={
                                "sessionId": f"load-{user.user_id}",
                                "documentId": user.doc_id,
                                "message": q,
                                "mode": "rag"
                            },
                            headers=headers,
                            timeout=aiohttp.ClientTimeout(total=120)) as resp:
                        latency = (time.time() - start) * 1000
                        
                        if resp.status == 200:
                            data = await resp.json()
                            session_results.append({
                                "user_id": user.user_id,
                                "status": 200,
                                "latency_ms": latency,
                                "confidence": data.get("confidence", "unknown"),
                                "rag_strategy": data.get("ragStrategy", "unknown")
                            })
                        elif resp.status == 429:
                            session_results.append({
                                "user_id": user.user_id,
                                "status": 429,
                                "latency_ms": latency,
                                "confidence": None,
                                "rag_strategy": "rate_limited"
                            })
                        else:
                            self.errors.append({
                                "user_id": user.user_id,
                                "status": resp.status,
                                "error": await resp.text()
                            })
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    self.errors.append({
                        "user_id": user.user_id,
                        "status": 0,
                        "error": str(e)
                    })
                
                # Small delay between requests (simulate user thinking)
                await asyncio.sleep(self.think_time)
        
        self.results.extend(session_results)

    async def run(self):
        """Run the load test."""
        print("\n🚀 Load Test Starting")
        print(f"   Users: {self.num_users}")
        print(f"   Duration: {self.duration}s")
        print(f"   Ramp-up: {self.ramp_up}s")
        print(f"   Target: {BASE_URL}")
        print()
        
        await self.setup()
        
        start_time = time.time()
        
        # Launch all users
        tasks = [self.user_session(user) for user in self.users]
        await asyncio.gather(*tasks)
        
        total_time = time.time() - start_time
        
        # Report
        self.report(total_time)

    def report(self, total_time: float):
        """Generate test report."""
        if not self.results:
            print("❌ No results collected")
            from collections import Counter
            print("Error status counts:",
                  dict(Counter(e.get("status") for e in self.errors)))
            for e in self.errors[:5]:
                print(f"  sample error: status={e.get('status')} "
                      f"error={str(e.get('error'))[:300]}")
        
        latencies = [r["latency_ms"] for r in self.results if r["status"] == 200]
        successes = len([r for r in self.results if r["status"] == 200])
        rate_limited = len([r for r in self.results if r["status"] == 429])
        total_requests = len(self.results)
        
        print("\n" + "=" * 60)
        print("LOAD TEST RESULTS")
        print("=" * 60)
        print(f"Total Requests: {total_requests}")
        print(f"Successful (200): {successes}")
        print(f"Rate Limited (429): {rate_limited}")
        print(f"Errors: {len(self.errors)}")
        print(f"Total Time: {total_time:.1f}s")
        print()
        
        if latencies:
            print("Latency (successful requests):")
            print(f"  Avg: {statistics.mean(latencies):.0f}ms")
            print(f"  Min: {min(latencies):.0f}ms")
            print(f"  Max: {max(latencies):.0f}ms")
            print(f"  P50: {statistics.median(latencies):.0f}ms")
            print(f"  P95: {sorted(latencies)[int(len(latencies)*0.95)]:.0f}ms")
            print(f"  P99: {sorted(latencies)[int(len(latencies)*0.99)]:.0f}ms")
            print()
        
        if total_time > 0:
            print(f"Throughput: {total_requests/total_time:.2f} req/s")
        if total_requests > 0:
            print(f"Success Rate: {successes/total_requests*100:.1f}%")
        else:
            print("Success Rate: n/a (no requests completed)")
        
        # Save results
        results_file = f"load_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(results_file, "w") as f:
            json.dump({
                "config": {
                    "users": self.num_users,
                    "duration": self.duration,
                    "ramp_up": self.ramp_up,
                    "think_time": self.think_time,
                },
                "summary": {
                    "total_requests": total_requests,
                    "successes": successes,
                    "rate_limited": rate_limited,
                    "errors": len(self.errors),
                    "total_time": total_time,
                    "throughput": total_requests/total_time if total_time > 0 else 0,
                    "success_rate": successes/total_requests if total_requests > 0 else 0,
                    "latency_avg": statistics.mean(latencies) if latencies else 0,
                    "latency_p95": sorted(latencies)[int(len(latencies)*0.95)] if latencies else 0
                },
                "results": self.results,
                "errors": self.errors[:100]  # Limit stored errors
            }, f, indent=2)
        
        print(f"\nResults saved to: {results_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load Test Smart Document Chatbot")
    parser.add_argument("--users", type=int, default=10, help="Number of concurrent users")
    parser.add_argument("--duration", type=int, default=30, help="Test duration in seconds")
    parser.add_argument("--ramp-up", type=int, default=0, help="Ramp-up time in seconds")
    parser.add_argument("--think-time", type=float, default=2.5, help="Pause between user requests")
    args = parser.parse_args()

    if args.users < 1 or args.duration < 1 or args.ramp_up < 0 or args.think_time < 0:
        parser.error("users and duration must be positive; ramp-up and think-time cannot be negative")

    test = LoadTest(args.users, args.duration, args.ramp_up, args.think_time)
    asyncio.run(test.run())
