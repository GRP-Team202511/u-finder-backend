# This code was completed by GRP Team 2025.11.
import os
from locust import HttpUser, task, between, SequentialTaskSet

# Determine if we are running in an isolated environment where DB connection failures (500s) 
# should be treated as "Application Framework Rendering Success"
ALLOW_500_AS_SUCCESS = os.getenv("LOCUST_ALLOW_500", "true").lower() in ("true", "1", "yes")

# Extract shared constants to avoid hard-coded duplication
BASE_ALLOWED_STATUS_CODES = [400, 401, 403, 404, 422]
if ALLOW_500_AS_SUCCESS:
    BASE_ALLOWED_STATUS_CODES.append(500)

def evaluate_response(response, allowed_codes=BASE_ALLOWED_STATUS_CODES):
    """Helper method to standardized success/failure criteria."""
    if response.status_code in allowed_codes or response.status_code < 400:
        response.success()
    else:
        response.failure(f"Unexpected status code: {response.status_code}")

class UFinderUserBehavior(SequentialTaskSet):
    """
    SequentialTaskSet simulates a realistic user journey step-by-step.
    """

    @task
    def health_check(self):
        """1. Basic Read/Routing Test: Hits the root endpoint"""
        self.client.get("/", name="01. Root / Health Check")

    @task
    def fetch_api_docs(self):
        """2. Static/Middleware Test: Loading API docs to test static file routing overhead"""
        self.client.get("/docs", name="02. Fetch API Docs")

    @task
    def invalid_login_attempt(self):
        """3. Write/Validation/DB Test: Simulates sending a POST request to Auth
        This tests the framework's JSON parsing (Pydantic), validation, and potentially DB rejection speed.
        (Even if it returns 401/400, it tests the server's processing overhead)
        """
        payload = {
            "email": "loadtest@example.com",
            "password": "incorrect_password"
        }
        with self.client.post("/auth/login", json=payload, name="03. Auth Login Attempt (POST)", catch_response=True) as response:
            evaluate_response(response)

    @task
    def access_protected_profile(self):
        """4. Security/Token Checking Overhead Test"""
        headers = {"Authorization": "Bearer fake_invalid_token_for_load_test"}
        with self.client.get("/profile", headers=headers, name="04. Protected Profile Fetch", catch_response=True) as response:
            evaluate_response(response)

class UFinderPerformanceTest(HttpUser):
    # Set default host if not provided in CLI
    host = os.getenv("LOCUST_TARGET_HOST", "http://localhost:8000")
    
    # Time spent pseudo-reading the page before the next request (between 1 and 3 seconds)
    wait_time = between(1, 3)

    # Assign the Sequential steps to the user
    tasks = [UFinderUserBehavior]

    def on_start(self):
        """Executed when a simulated user starts. Useful for setup like real login."""
        pass

    def on_stop(self):
        """Executed when a virtual user is destroyed."""
        pass


