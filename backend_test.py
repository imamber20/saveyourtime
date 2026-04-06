#!/usr/bin/env python3
"""
Content Memory App - Backend API Testing
Tests all API endpoints for the Content Memory application.
"""

import requests
import sys
import json
import time
from datetime import datetime

class ContentMemoryAPITester:
    def __init__(self, base_url="https://48849390-5964-4aeb-8246-171f9a335447.preview.emergentagent.com"):
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers.update({'Content-Type': 'application/json'})
        self.tests_run = 0
        self.tests_passed = 0
        self.test_results = []
        self.user_id = None
        self.item_id = None
        self.collection_id = None

    def log_test(self, name, success, details=""):
        """Log test result"""
        self.tests_run += 1
        if success:
            self.tests_passed += 1
            print(f"✅ {name}")
        else:
            print(f"❌ {name} - {details}")
        
        self.test_results.append({
            "test": name,
            "success": success,
            "details": details
        })

    def run_test(self, name, method, endpoint, expected_status, data=None, params=None):
        """Run a single API test"""
        url = f"{self.base_url}/{endpoint}"
        
        try:
            if method == 'GET':
                response = self.session.get(url, params=params)
            elif method == 'POST':
                response = self.session.post(url, json=data)
            elif method == 'PUT':
                response = self.session.put(url, json=data)
            elif method == 'DELETE':
                response = self.session.delete(url)

            success = response.status_code == expected_status
            details = f"Status: {response.status_code}"
            if not success:
                details += f", Expected: {expected_status}"
                try:
                    error_detail = response.json().get('detail', 'No detail')
                    details += f", Error: {error_detail}"
                except:
                    details += f", Response: {response.text[:100]}"

            self.log_test(name, success, details)
            return success, response.json() if success and response.content else {}

        except Exception as e:
            self.log_test(name, False, f"Exception: {str(e)}")
            return False, {}

    def test_health(self):
        """Test health endpoint"""
        success, response = self.run_test(
            "Health Check",
            "GET",
            "api/health",
            200
        )
        return success

    def test_register(self):
        """Test user registration"""
        test_email = f"test_{int(time.time())}@example.com"
        success, response = self.run_test(
            "User Registration",
            "POST",
            "api/auth/register",
            200,
            data={
                "email": test_email,
                "password": "testpass123",
                "name": "Test User"
            }
        )
        if success and 'id' in response:
            self.user_id = response['id']
        return success

    def test_login_admin(self):
        """Test admin login"""
        success, response = self.run_test(
            "Admin Login",
            "POST",
            "api/auth/login",
            200,
            data={
                "email": "admin@example.com",
                "password": "admin123"
            }
        )
        if success and 'id' in response:
            self.user_id = response['id']
        return success

    def test_auth_me(self):
        """Test get current user"""
        success, response = self.run_test(
            "Get Current User",
            "GET",
            "api/auth/me",
            200
        )
        return success

    def test_logout(self):
        """Test logout"""
        success, response = self.run_test(
            "Logout",
            "POST",
            "api/auth/logout",
            200
        )
        return success

    def test_save_youtube_url(self):
        """Test saving a YouTube Shorts URL"""
        success, response = self.run_test(
            "Save YouTube Shorts URL",
            "POST",
            "api/save",
            200,
            data={
                "url": "https://www.youtube.com/shorts/dQw4w9WgXcQ"
            }
        )
        if success and 'item_id' in response:
            self.item_id = response['item_id']
        return success

    def test_save_invalid_url(self):
        """Test saving invalid URL"""
        success, response = self.run_test(
            "Save Invalid URL",
            "POST",
            "api/save",
            400,
            data={
                "url": "not-a-valid-url"
            }
        )
        return success

    def test_save_unsupported_platform(self):
        """Test saving unsupported platform URL"""
        success, response = self.run_test(
            "Save Unsupported Platform",
            "POST",
            "api/save",
            400,
            data={
                "url": "https://twitter.com/some-tweet"
            }
        )
        return success

    def test_duplicate_url_detection(self):
        """Test duplicate URL detection"""
        # First save
        self.run_test(
            "Save URL First Time",
            "POST",
            "api/save",
            200,
            data={
                "url": "https://www.youtube.com/shorts/test123"
            }
        )
        
        # Try to save same URL again
        success, response = self.run_test(
            "Duplicate URL Detection",
            "POST",
            "api/save",
            200,
            data={
                "url": "https://www.youtube.com/shorts/test123"
            }
        )
        # Should return duplicate status
        if success and response.get('status') == 'duplicate':
            return True
        return False

    def test_list_items(self):
        """Test listing items"""
        success, response = self.run_test(
            "List Items",
            "GET",
            "api/items",
            200
        )
        return success

    def test_get_item_detail(self):
        """Test getting item detail"""
        if not self.item_id:
            self.log_test("Get Item Detail", False, "No item_id available")
            return False
            
        success, response = self.run_test(
            "Get Item Detail",
            "GET",
            f"api/items/{self.item_id}",
            200
        )
        return success

    def test_update_item(self):
        """Test updating item"""
        if not self.item_id:
            self.log_test("Update Item", False, "No item_id available")
            return False
            
        success, response = self.run_test(
            "Update Item",
            "PUT",
            f"api/items/{self.item_id}",
            200,
            data={
                "title": "Updated Test Title",
                "notes": "Test notes"
            }
        )
        return success

    def test_create_collection(self):
        """Test creating collection"""
        success, response = self.run_test(
            "Create Collection",
            "POST",
            "api/collections",
            200,
            data={
                "name": "Test Collection",
                "description": "A test collection"
            }
        )
        if success and 'id' in response:
            self.collection_id = response['id']
        return success

    def test_list_collections(self):
        """Test listing collections"""
        success, response = self.run_test(
            "List Collections",
            "GET",
            "api/collections",
            200
        )
        return success

    def test_add_item_to_collection(self):
        """Test adding item to collection"""
        if not self.collection_id or not self.item_id:
            self.log_test("Add Item to Collection", False, "Missing collection_id or item_id")
            return False
            
        success, response = self.run_test(
            "Add Item to Collection",
            "POST",
            f"api/collections/{self.collection_id}/items",
            200,
            data={
                "item_id": self.item_id
            }
        )
        return success

    def test_search_items(self):
        """Test searching items"""
        success, response = self.run_test(
            "Search Items",
            "GET",
            "api/search",
            200,
            params={"q": "test"}
        )
        return success

    def test_get_map_items(self):
        """Test getting map items"""
        success, response = self.run_test(
            "Get Map Items",
            "GET",
            "api/map",
            200
        )
        return success

    def test_get_categories(self):
        """Test getting categories"""
        success, response = self.run_test(
            "Get Categories",
            "GET",
            "api/categories",
            200
        )
        return success

    def test_delete_item(self):
        """Test deleting item"""
        if not self.item_id:
            self.log_test("Delete Item", False, "No item_id available")
            return False
            
        success, response = self.run_test(
            "Delete Item",
            "DELETE",
            f"api/items/{self.item_id}",
            200
        )
        return success

    def run_all_tests(self):
        """Run all tests in sequence"""
        print("🚀 Starting Content Memory API Tests")
        print(f"📍 Testing against: {self.base_url}")
        print("=" * 60)

        # Health check first
        if not self.test_health():
            print("❌ Health check failed - stopping tests")
            return False

        # Auth flow tests
        print("\n🔐 Testing Authentication Flow...")
        self.test_login_admin()
        self.test_auth_me()
        
        # Save flow tests
        print("\n💾 Testing Save Flow...")
        self.test_save_youtube_url()
        self.test_save_invalid_url()
        self.test_save_unsupported_platform()
        self.test_duplicate_url_detection()

        # Items tests
        print("\n📄 Testing Items Management...")
        self.test_list_items()
        self.test_get_item_detail()
        self.test_update_item()

        # Collections tests
        print("\n📁 Testing Collections...")
        self.test_create_collection()
        self.test_list_collections()
        self.test_add_item_to_collection()

        # Search and other features
        print("\n🔍 Testing Search & Other Features...")
        self.test_search_items()
        self.test_get_map_items()
        self.test_get_categories()

        # Cleanup
        print("\n🧹 Cleanup...")
        self.test_delete_item()
        self.test_logout()

        # Print summary
        print("\n" + "=" * 60)
        print(f"📊 Test Results: {self.tests_passed}/{self.tests_run} passed")
        
        if self.tests_passed == self.tests_run:
            print("🎉 All tests passed!")
            return True
        else:
            print("⚠️  Some tests failed")
            return False

def main():
    """Main test runner"""
    tester = ContentMemoryAPITester()
    success = tester.run_all_tests()
    
    # Save detailed results
    with open('/app/test_reports/backend_test_results.json', 'w') as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "total_tests": tester.tests_run,
            "passed_tests": tester.tests_passed,
            "success_rate": tester.tests_passed / tester.tests_run if tester.tests_run > 0 else 0,
            "results": tester.test_results
        }, f, indent=2)
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())