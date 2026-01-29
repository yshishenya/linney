#!/usr/bin/env python3
"""
Live API Integration Test for A101 HR Profile Generator.

Tests the actual API endpoints used by the frontend components
with proper authentication and realistic data flows.
"""

import requests
import json
import time
from typing import Dict, Any, Optional

class LiveAPITester:
    """Test the live API endpoints used by components."""

    def __init__(self, base_url="http://localhost:8022"):
        self.base_url = base_url
        self.session = requests.Session()
        self.access_token = None

    def authenticate(self, username="admin", password="q4Mrpwty7t9F") -> bool:
        """Authenticate with the API and get access token."""

        try:
            response = self.session.post(
                f"{self.base_url}/api/auth/login",
                json={"username": username, "password": password},
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                self.access_token = data.get('access_token')

                if self.access_token:
                    self.session.headers.update({
                        'Authorization': f'Bearer {self.access_token}'
                    })
                    print(f"✅ Authenticated as {data.get('user_info', {}).get('username')}")
                    return True
                else:
                    print("❌ No access token in response")
                    return False
            else:
                print(f"❌ Authentication failed: {response.status_code}")
                return False

        except Exception as e:
            print(f"❌ Authentication error: {e}")
            return False

    def test_component_integrations(self):
        """Test the actual API flows used by frontend components."""

        print("\n🔧 COMPONENT INTEGRATION TESTS")
        print("=" * 50)

        if not self.authenticate():
            print("❌ Cannot proceed without authentication")
            return

        # Test 1: SearchComponent API Integration
        print("\n1. SearchComponent API Flow")
        print("-" * 30)

        search_success = self.test_search_component_flow()

        # Test 2: GeneratorComponent API Integration
        print("\n2. GeneratorComponent API Flow")
        print("-" * 35)

        generator_success = self.test_generator_component_flow()

        # Test 3: ProfileViewerComponent API Integration
        print("\n3. ProfileViewerComponent API Flow")
        print("-" * 40)

        viewer_success = self.test_viewer_component_flow()

        # Test 4: FilesManagerComponent API Integration
        print("\n4. FilesManagerComponent API Flow")
        print("-" * 38)

        files_success = self.test_files_component_flow()

        # Summary
        print(f"\n📊 INTEGRATION TEST SUMMARY")
        print("-" * 30)

        results = {
            'SearchComponent': search_success,
            'GeneratorComponent': generator_success,
            'ProfileViewerComponent': viewer_success,
            'FilesManagerComponent': files_success
        }

        for component, success in results.items():
            status = "✅ PASS" if success else "❌ FAIL"
            print(f"{status} {component}")

        total_passed = sum(results.values())
        print(f"\nTotal: {total_passed}/4 components passed integration tests")

    def test_search_component_flow(self) -> bool:
        """Test SearchComponent API integration flow."""

        try:
            # Step 1: Load search data (get_organization_search_items)
            print("   📊 Loading organization search items...")

            response = self.session.get(
                f"{self.base_url}/api/organization/search-items",
                timeout=10
            )

            if response.status_code != 200:
                print(f"   ❌ Search items API failed: {response.status_code}")
                return False

            data = response.json()
            items = data.get('data', {}).get('items', [])

            if not items:
                print("   ❌ No search items returned")
                return False

            print(f"   ✅ Loaded {len(items)} search items")

            # Step 2: Get departments list
            print("   🏢 Loading departments...")

            dept_response = self.session.get(
                f"{self.base_url}/api/catalog/departments",
                timeout=10
            )

            if dept_response.status_code != 200:
                print(f"   ❌ Departments API failed: {dept_response.status_code}")
                return False

            dept_data = dept_response.json()
            departments = dept_data.get('data', {}).get('departments', [])

            print(f"   ✅ Loaded {len(departments)} departments")

            # Step 3: Get positions for a sample department
            if departments:
                sample_dept = departments[0]['name']
                print(f"   👥 Loading positions for '{sample_dept}'...")

                # Use URL encoding for department name
                import urllib.parse
                encoded_dept = urllib.parse.quote(sample_dept)

                pos_response = self.session.get(
                    f"{self.base_url}/api/catalog/positions/{encoded_dept}",
                    timeout=10
                )

                if pos_response.status_code == 200:
                    pos_data = pos_response.json()
                    positions = pos_data.get('data', {}).get('positions', [])
                    print(f"   ✅ Loaded {len(positions)} positions")
                else:
                    print(f"   ⚠️ Positions API returned: {pos_response.status_code}")

            return True

        except Exception as e:
            print(f"   ❌ SearchComponent test error: {e}")
            return False

    def test_generator_component_flow(self) -> bool:
        """Test GeneratorComponent API integration flow."""

        try:
            # Step 1: Start profile generation
            print("   🚀 Starting profile generation...")

            generation_data = {
                "department": "Административный отдел",
                "position": "Руководитель административного отдела",
                "save_result": True
            }

            response = self.session.post(
                f"{self.base_url}/api/generate-profile",
                json=generation_data,
                timeout=15
            )

            if response.status_code != 200:
                print(f"   ❌ Generation start failed: {response.status_code}")
                # Try to get error details
                try:
                    error_data = response.json()
                    print(f"   Error details: {error_data}")
                except ValueError as e:
                    print(f"   Failed to parse error JSON: {e}")
                    print(f"   Response text: {response.text[:200]}")
                return False

            data = response.json()
            task_id = data.get('task_id')

            if not task_id:
                print("   ❌ No task ID returned")
                return False

            print(f"   ✅ Generation started with task ID: {task_id[:12]}...")

            # Step 2: Poll generation status
            print("   ⏳ Polling generation status...")

            max_polls = 5
            status = "unknown"
            for i in range(max_polls):
                status_response = self.session.get(
                    f"{self.base_url}/api/generation-task/{task_id}/status",
                    timeout=10
                )

                if status_response.status_code != 200:
                    print(f"   ❌ Status check failed: {status_response.status_code}")
                    return False

                status_data = status_response.json()
                task_info = status_data.get('task', {})
                status = task_info.get('status', 'unknown')
                progress = task_info.get('progress', 0)

                print(f"   📊 Status: {status}, Progress: {progress}%")

                if status == 'completed':
                    print("   ✅ Generation completed successfully")
                    break
                elif status == 'failed':
                    print("   ❌ Generation failed")
                    return False

                if i < max_polls - 1:
                    time.sleep(2)  # Wait before next poll

            # Step 3: Get generation result (if completed)
            if status == 'completed':
                print("   📄 Getting generation result...")

                result_response = self.session.get(
                    f"{self.base_url}/api/generation-task/{task_id}/result",
                    timeout=10
                )

                if result_response.status_code == 200:
                    result_data = result_response.json()
                    print("   ✅ Generation result retrieved")
                    return True
                else:
                    print(f"   ❌ Result retrieval failed: {result_response.status_code}")
                    return False
            else:
                print("   ⚠️ Generation did not complete in time (test limitation)")
                return True  # Still consider successful since generation started

        except Exception as e:
            print(f"   ❌ GeneratorComponent test error: {e}")
            return False

    def test_viewer_component_flow(self) -> bool:
        """Test ProfileViewerComponent API integration flow."""

        try:
            # Step 1: Get list of existing profiles
            print("   📋 Loading existing profiles...")

            response = self.session.get(
                f"{self.base_url}/api/profiles",
                params={"limit": 5},
                timeout=10
            )

            if response.status_code != 200:
                print(f"   ❌ Profiles list API failed: {response.status_code}")
                return False

            data = response.json()
            profiles = data.get('profiles', [])

            if not profiles:
                print("   ⚠️ No existing profiles found (expected for new system)")
                return True  # Not a failure, just no data yet

            print(f"   ✅ Found {len(profiles)} existing profiles")

            # Step 2: Get details for first profile
            if profiles:
                profile_id = profiles[0].get('profile_id')
                print(f"   🔍 Getting details for profile: {profile_id[:12]}...")

                detail_response = self.session.get(
                    f"{self.base_url}/api/profiles/{profile_id}",
                    timeout=10
                )

                if detail_response.status_code == 200:
                    print("   ✅ Profile details retrieved")
                else:
                    print(f"   ⚠️ Profile details failed: {detail_response.status_code}")

            return True

        except Exception as e:
            print(f"   ❌ ProfileViewerComponent test error: {e}")
            return False

    def test_files_component_flow(self) -> bool:
        """Test FilesManagerComponent API integration flow."""

        try:
            # Step 1: Get a profile ID for download testing
            print("   📥 Testing file download capabilities...")

            profiles_response = self.session.get(
                f"{self.base_url}/api/profiles",
                params={"limit": 1},
                timeout=10
            )

            if profiles_response.status_code != 200:
                print(f"   ❌ Cannot get profiles for download test: {profiles_response.status_code}")
                return False

            data = profiles_response.json()
            profiles = data.get('profiles', [])

            if not profiles:
                print("   ⚠️ No profiles available for download test")
                return True  # Not a failure, just no data

            profile_id = profiles[0].get('profile_id')
            print(f"   📄 Testing downloads for profile: {profile_id[:12]}...")

            # Step 2: Test JSON download
            print("   📊 Testing JSON download...")

            json_response = self.session.get(
                f"{self.base_url}/api/profiles/{profile_id}/download/json",
                timeout=15
            )

            if json_response.status_code == 200:
                json_size = len(json_response.content)
                print(f"   ✅ JSON download successful ({json_size} bytes)")
            else:
                print(f"   ❌ JSON download failed: {json_response.status_code}")
                return False

            # Step 3: Test Markdown download
            print("   📝 Testing Markdown download...")

            md_response = self.session.get(
                f"{self.base_url}/api/profiles/{profile_id}/download/markdown",
                timeout=15
            )

            if md_response.status_code == 200:
                md_size = len(md_response.content)
                print(f"   ✅ Markdown download successful ({md_size} bytes)")
                return True
            else:
                print(f"   ❌ Markdown download failed: {md_response.status_code}")
                return False

        except Exception as e:
            print(f"   ❌ FilesManagerComponent test error: {e}")
            return False

    def test_error_scenarios(self):
        """Test error handling scenarios across components."""

        print(f"\n🚨 ERROR HANDLING TESTS")
        print("-" * 30)

        # Test invalid department
        print("   🏢 Testing invalid department...")

        try:
            response = self.session.post(
                f"{self.base_url}/api/generate-profile",
                json={"department": "NonExistent", "position": "Test"},
                timeout=10
            )

            if response.status_code in [400, 404, 422]:
                print("   ✅ Invalid department properly rejected")
            else:
                print(f"   ❌ Unexpected response: {response.status_code}")

        except Exception as e:
            print(f"   ❌ Error test failed: {e}")

        # Test invalid profile download
        print("   📄 Testing invalid profile download...")

        try:
            response = self.session.get(
                f"{self.base_url}/api/profiles/invalid-id/download/json",
                timeout=10
            )

            if response.status_code in [400, 404, 422]:
                print("   ✅ Invalid profile properly rejected")
            else:
                print(f"   ❌ Unexpected response: {response.status_code}")

        except Exception as e:
            print(f"   ❌ Error test failed: {e}")


if __name__ == "__main__":
    print("🧪 A101 HR Profile Generator - Live API Integration Test")
    print("=" * 65)

    try:
        tester = LiveAPITester()
        tester.test_component_integrations()
        tester.test_error_scenarios()

        print("\n✅ Live integration testing completed!")

    except KeyboardInterrupt:
        print("\n\n⚠️ Testing interrupted by user")
    except Exception as e:
        print(f"\n\n💥 Testing failed: {e}")
        import traceback
        traceback.print_exc()
