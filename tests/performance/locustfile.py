from locust import HttpUser, task, between, SequentialTaskSet

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
            # Note: In a DB-disconnected local environment, this inherently returns 500 (Internal Server Error).
            # We explicitly catch 500, 422, 401, etc. as "success" strictly to benchmark the 
            # pure API routing, request parsing, and error-handling framework overhead.
            if response.status_code in [400, 401, 403, 404, 422, 500]:
                response.success()
            else:
                response.failure(f"Unexpected status code: {response.status_code}")

    @task
    def access_protected_profile(self):
        """4. Security/Token Checking Overhead Test"""
        headers = {"Authorization": "Bearer fake_invalid_token_for_load_test"}
        with self.client.get("/profile", headers=headers, name="04. Protected Profile Fetch", catch_response=True) as response:
            # Same rationale here: 500 is treated as a successful "framework roundtrip" for this specific benchmark.
            if response.status_code in [401, 403, 404, 500]:
                response.success()
            else:
                response.failure(f"Unexpected status code: {response.status_code}")


class UFinderPerformanceTest(HttpUser):
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
