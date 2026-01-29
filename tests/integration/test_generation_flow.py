#!/usr/bin/env python3
"""
End-to-end test of the profile generation workflow
Tests the complete flow from search to generation to download
"""
import asyncio
import httpx
import json
import time

class GenerationFlowTester:
    def __init__(self):
        self.base_url = "http://localhost:8022"
        self.token = None

    async def login(self):
        """Authenticate with the API"""
        login_data = {"username": "admin", "password": "q4Mrpwty7t9F"}

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/api/auth/login",
                json=login_data,
                timeout=10.0
            )

            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    self.token = data.get("access_token")
                    return True

        return False

    def get_headers(self):
        """Get authorization headers"""
        return {"Authorization": f"Bearer {self.token}"}

    async def test_search_functionality(self):
        """Test search items API"""
        print("\n🔍 Testing Search Functionality")

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/api/organization/search-items",
                headers=self.get_headers(),
                timeout=10.0
            )

            if response.status_code == 200:
                data = response.json()
                items = data.get("data", {}).get("items", [])
                print(f"✅ Found {len(items)} search items")

                # Show some examples
                for i, item in enumerate(items[:3]):
                    print(f"   {i+1}. {item.get('name', 'Unknown')} ({item.get('positions_count', 0)} positions)")

                return items
            else:
                print(f"❌ Search failed: {response.status_code}")
                return []

    async def test_generation_start(self, department="ДИТ", position="Java-разработчик"):
        """Test starting profile generation"""
        print(f"\n🚀 Testing Generation Start: {position} in {department}")

        generation_data = {
            "department": department,
            "position": position,
            "temperature": 0.1,
            "save_result": True
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/api/generation/start",
                json=generation_data,
                headers=self.get_headers(),
                timeout=15.0
            )

            if response.status_code == 200:
                data = response.json()
                if data.get("task_id"):
                    task_id = data.get("task_id")
                    print(f"✅ Generation started, task ID: {task_id[:8]}...")
                    return task_id
                else:
                    print(f"❌ Generation failed: {data}")
                    return None
            else:
                print(f"❌ Generation request failed: {response.status_code}")
                print(f"   Response: {response.text}")
                return None

    async def test_generation_monitoring(self, task_id, max_wait=180):
        """Monitor generation progress"""
        print(f"\n⏳ Monitoring Generation Progress (max {max_wait}s)")

        start_time = time.time()
        last_progress = -1

        async with httpx.AsyncClient() as client:
            while time.time() - start_time < max_wait:
                try:
                    response = await client.get(
                        f"{self.base_url}/api/generation/{task_id}/status",
                        headers=self.get_headers(),
                        timeout=10.0
                    )

                    if response.status_code == 200:
                        data = response.json()
                        task_data = data.get("task", {})
                        status = task_data.get("status")
                        progress = task_data.get("progress", 0)
                        current_step = task_data.get("current_step", "Processing...")

                        # Show progress updates
                        if progress != last_progress:
                            elapsed = time.time() - start_time
                            print(f"   {elapsed:.1f}s: {status} - {progress}% - {current_step}")
                            last_progress = progress

                        if status == "completed":
                            print("✅ Generation completed successfully!")
                            return True
                        elif status == "failed":
                            error_msg = task_data.get("error_message", "Unknown error")
                            print(f"❌ Generation failed: {error_msg}")
                            return False
                        elif status == "cancelled":
                            print("⚠️ Generation was cancelled")
                            return False

                    await asyncio.sleep(5)  # Check every 5 seconds

                except Exception as e:
                    print(f"⚠️ Status check error: {e}")
                    await asyncio.sleep(5)

        print(f"⏰ Generation timeout after {max_wait}s")
        return False

    async def test_generation_result(self, task_id):
        """Get and analyze generation result"""
        print(f"\n📄 Testing Generation Result")

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/api/generation/{task_id}/result",
                headers=self.get_headers(),
                timeout=10.0
            )

            if response.status_code == 200:
                data = response.json()
                if data.get("success") and data.get("profile"):
                    profile = data.get("profile", {})
                    metadata = data.get("metadata", {})

                    print("✅ Generation result retrieved")
                    print(f"   Profile ID: {data.get('profile_id', 'N/A')}")
                    print(f"   Position: {profile.get('position_title', 'N/A')}")
                    print(f"   Department: {profile.get('department', 'N/A')}")

                    # Check content structure
                    content_sections = ["job_summary", "responsibility_areas", "professional_skills", "kpi"]
                    for section in content_sections:
                        if section in profile:
                            print(f"   ✅ {section}: Present")
                        else:
                            print(f"   ❌ {section}: Missing")

                    # Check metadata
                    gen_time = metadata.get("generation_time_seconds", 0)
                    tokens_used = metadata.get("tokens_used", {})
                    print(f"   Generation time: {gen_time:.1f}s")
                    if isinstance(tokens_used, dict):
                        total_tokens = tokens_used.get("total", 0)
                        print(f"   Tokens used: {total_tokens:,}")

                    return data.get("profile_id")
                else:
                    print(f"❌ Invalid result structure: {data}")
                    return None
            else:
                print(f"❌ Result fetch failed: {response.status_code}")
                return None

    async def test_file_downloads(self, profile_id):
        """Test file download functionality"""
        print(f"\n📥 Testing File Downloads")

        formats = ["json", "md"]
        download_results = {}

        async with httpx.AsyncClient() as client:
            for file_format in formats:
                try:
                    response = await client.get(
                        f"{self.base_url}/api/profiles/{profile_id}/download/{file_format}",
                        headers=self.get_headers(),
                        timeout=15.0
                    )

                    if response.status_code == 200:
                        content_length = len(response.content)
                        print(f"   ✅ {file_format.upper()}: {content_length:,} bytes")
                        download_results[file_format] = content_length

                        # Basic content validation
                        if file_format == "json":
                            try:
                                json_data = json.loads(response.content)
                                print(f"      Valid JSON with {len(json_data)} keys")
                            except (json.JSONDecodeError, TypeError, UnicodeDecodeError) as e:
                                print(f"      ⚠️ Invalid JSON content: {e}")

                        elif file_format == "md":
                            content = response.content.decode('utf-8')
                            if "# " in content and len(content) > 100:
                                print(f"      Valid Markdown content")
                            else:
                                print(f"      ⚠️ Suspicious Markdown content")

                    else:
                        print(f"   ❌ {file_format.upper()}: {response.status_code}")
                        download_results[file_format] = 0

                except Exception as e:
                    print(f"   ❌ {file_format.upper()}: {e}")
                    download_results[file_format] = 0

        return download_results

    async def test_profiles_list(self):
        """Test profiles listing functionality"""
        print(f"\n📋 Testing Profiles List")

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/api/profiles/",
                headers=self.get_headers(),
                params={"limit": 10},
                timeout=10.0
            )

            if response.status_code == 200:
                data = response.json()
                profiles = data.get("profiles", [])
                pagination = data.get("pagination", {})

                print(f"✅ Found {len(profiles)} profiles")
                print(f"   Total in system: {pagination.get('total', 0)}")

                if profiles:
                    latest = profiles[0]
                    print(f"   Latest: {latest.get('position', 'N/A')} in {latest.get('department', 'N/A')}")

                return profiles
            else:
                print(f"❌ Profiles list failed: {response.status_code}")
                return []

    async def run_complete_test(self):
        """Run the complete end-to-end test"""
        print("🧪 A101 HR Profile Generator - End-to-End Test")
        print("=" * 60)

        # Step 1: Login
        print("🔐 Step 1: Authentication")
        if not await self.login():
            print("❌ Login failed - aborting test")
            return False

        print("✅ Authentication successful")

        # Step 2: Search functionality
        search_items = await self.test_search_functionality()
        if not search_items:
            print("❌ Search failed - aborting test")
            return False

        # Step 3: Profiles list
        profiles = await self.test_profiles_list()

        # Step 4: Generation (only if we have valid search items)
        if search_items:
            # Find a good test case
            test_department = "ДИТ"
            test_position = "Java-разработчик"

            # Look for a real example from search items
            for item in search_items:
                if item.get("positions_count", 0) > 0:
                    positions = item.get("positions", [])
                    if positions and "разработчик" in positions[0].lower():
                        test_department = item.get("name", test_department)
                        test_position = positions[0]
                        break

            print(f"\n🎯 Using test case: {test_position} in {test_department}")

            # Start generation
            task_id = await self.test_generation_start(test_department, test_position)

            if task_id:
                # Monitor progress
                success = await self.test_generation_monitoring(task_id)

                if success:
                    # Get result
                    profile_id = await self.test_generation_result(task_id)

                    if profile_id:
                        # Test downloads
                        downloads = await self.test_file_downloads(profile_id)

                        # Final summary
                        print("\n" + "=" * 60)
                        print("📊 Test Summary")
                        print(f"✅ Authentication: Success")
                        print(f"✅ Search items: {len(search_items)}")
                        print(f"✅ Profiles list: {len(profiles)}")
                        print(f"✅ Generation: Success")
                        print(f"✅ Profile ID: {profile_id}")

                        for fmt, size in downloads.items():
                            status = "✅" if size > 0 else "❌"
                            print(f"{status} Download {fmt.upper()}: {size:,} bytes")

                        print("\n🎉 All tests completed successfully!")
                        return True

        print("\n⚠️ Some tests were skipped or failed")
        return False

async def main():
    tester = GenerationFlowTester()
    success = await tester.run_complete_test()
    return 0 if success else 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
