"""
Automated Test Suite for ChatV2 Campaign Assistant
Comprehensive tests for all scenarios
"""

import pytest

pytestmark = pytest.mark.integration

import requests
import os
import json
import time
from datetime import datetime
from typing import Dict, Any
from colorama import init, Fore, Style  # type: ignore[import-untyped]

init(autoreset=True)

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
CLIENT_CODE = os.getenv("CLIENT_CODE", "TEST_CLIENT")


class _TestStats:
    def __init__(self):
        self.total = 0
        self.passed = 0
        self.failed = 0
        self.failed_tests = []


stats = _TestStats()


def print_header(text: str):
    print(f"\n{Fore.CYAN}{'='*80}")
    print(f"{Fore.CYAN}{text:^80}")
    print(f"{Fore.CYAN}{'='*80}{Style.RESET_ALL}")


def print_test_name(name: str):
    print(f"\n{Fore.YELLOW}>> TEST: {name}{Style.RESET_ALL}")


def print_step(step_num: int, message: str):
    print(f"{Fore.WHITE}  Step {step_num}: {message}{Style.RESET_ALL}")


def print_success(message: str):
    print(f"{Fore.GREEN}  OK: {message}{Style.RESET_ALL}")


def print_error(message: str):
    print(f"{Fore.RED}  FAIL: {message}{Style.RESET_ALL}")


def print_response(response: Dict):
    print(f"{Fore.MAGENTA}  Response: {json.dumps(response, indent=2)}{Style.RESET_ALL}")


class ChatV2TestClient:
    """Client for testing ChatV2 API"""

    def __init__(self, base_url: str = BASE_URL, client_code: str = CLIENT_CODE):
        self.base_url = base_url
        self.client_code = client_code
        self.session_id: str | None = None

    def start_session(self) -> str:
        response = requests.post(f"{self.base_url}/api/ds/chatv2/start-session")
        response.raise_for_status()
        session_id: str = response.json()["session_id"]
        self.session_id = session_id
        return session_id

    def send_message(self, message: str) -> Dict[str, Any]:
        # TODO: update to use /stream SSE endpoint (non-stream endpoint removed)
        if not self.session_id:
            raise ValueError("No active session. Call start_session() first.")

        response = requests.post(
            f"{self.base_url}/api/ds/chatv2/{self.session_id}",
            params={"message": message},
            headers={
                "content-type": "application/json",
                "clientCode": self.client_code,
            },
        )

        if response.status_code != 200:
            try:
                return response.json()
            except json.JSONDecodeError:
                return {
                    "status": "error",
                    "message": f"HTTP {response.status_code}",
                    "details": response.text,
                }

        return response.json()

    def get_session(self) -> Dict[str, Any]:
        if not self.session_id:
            return {"error": "No active session"}
        response = requests.get(f"{self.base_url}/api/ds/chatv2/{self.session_id}")
        return response.json()

    def end_session(self) -> Dict[str, Any]:
        if not self.session_id:
            return {"error": "No active session"}

        response = requests.post(
            f"{self.base_url}/api/ds/chatv2/end-session/{self.session_id}",
            headers={"content-type": "application/json"},
        )

        self.session_id = None

        if response.status_code == 200:
            return response.json()
        else:
            return {"error": f"HTTP {response.status_code}", "details": response.text}


def assert_status(actual: str, expected: str, test_name: str):
    stats.total += 1
    if actual == expected:
        print_success(f"Status: {actual} (Expected: {expected})")
        stats.passed += 1
        return True
    else:
        print_error(f"Status mismatch! Got: {actual}, Expected: {expected}")
        stats.failed += 1
        stats.failed_tests.append(test_name)
        return False


def assert_contains(text: str, substring: str, description: str, test_name: str):
    stats.total += 1
    if substring.lower() in text.lower():
        print_success(f"{description}: Contains '{substring}'")
        stats.passed += 1
        return True
    else:
        print_error(f"{description}: Does NOT contain '{substring}'")
        stats.failed += 1
        stats.failed_tests.append(test_name)
        return False


def assert_field_extracted(response: Dict, field_name: str, test_name: str):
    stats.total += 1
    collected = response.get("collected_data", {})
    if collected and field_name in collected:
        print_success(f"Field extracted: {field_name}")
        stats.passed += 1
        return True
    else:
        print_error(f"Field NOT extracted: {field_name}")
        stats.failed += 1
        stats.failed_tests.append(test_name)
        return False


def assert_progress(response: Dict, expected_progress: str, test_name: str):
    stats.total += 1
    actual = response.get("progress", "")
    if actual == expected_progress:
        print_success(f"Progress: {actual}")
        stats.passed += 1
        return True
    else:
        print_error(f"Progress mismatch! Got: {actual}, Expected: {expected_progress}")
        stats.failed += 1
        stats.failed_tests.append(test_name)
        return False


def assert_reply_not_empty(response: Dict, test_name: str):
    """Assert that reply is not empty - critical for continuation responses"""
    stats.total += 1
    reply = response.get("reply", "")
    if reply and reply.strip():
        print_success(f"Reply not empty: '{reply[:50]}...'")
        stats.passed += 1
        return True
    else:
        print_error("Reply is EMPTY (should have content)")
        stats.failed += 1
        stats.failed_tests.append(test_name)
        return False


# CATEGORY 1: GREETING TESTS


def test_simple_greeting():
    test_name = "Simple Greeting"
    print_test_name(test_name)

    client = ChatV2TestClient()
    client.start_session()

    print_step(1, "Send: 'hi'")
    response = client.send_message("hi")
    print_response(response)

    assert_status(response.get("status"), "in_progress", test_name)
    assert_reply_not_empty(response, test_name)

    client.end_session()


def test_greeting_with_details():
    test_name = "Greeting with Details"
    print_test_name(test_name)

    client = ChatV2TestClient()
    client.start_session()

    print_step(1, "Send: 'Hello, I run TechCorp, budget is 10k'")
    response = client.send_message("Hello, I run TechCorp, budget is 10k")
    print_response(response)

    assert_status(response.get("status"), "in_progress", test_name)
    assert_field_extracted(response, "businessName", test_name)
    assert_field_extracted(response, "budget", test_name)

    client.end_session()


# CATEGORY 2: ALL-AT-ONCE INPUT


def test_all_at_once_standard():
    test_name = "All-at-Once Standard"
    print_test_name(test_name)

    client = ChatV2TestClient()
    client.start_session()

    print_step(1, "Send all details at once")
    response = client.send_message(
        "Setup campaign for Fresh Bakery, website is https://freshbakery.com, budget 5000, 7 days"
    )
    print_response(response)

    # Should have all fields and move to MCC selection
    assert_field_extracted(response, "businessName", test_name)
    assert_field_extracted(response, "websiteURL", test_name)
    assert_field_extracted(response, "budget", test_name)
    assert_field_extracted(response, "durationDays", test_name)

    client.end_session()


def test_all_at_once_informal():
    test_name = "All-at-Once Informal"
    print_test_name(test_name)

    client = ChatV2TestClient()
    client.start_session()

    print_step(1, "Send: 'I run Pizza Palace, pizzapalace.com, 15k budget, 2 weeks'")
    response = client.send_message(
        "I run Pizza Palace, pizzapalace.com, 15k budget, 2 weeks"
    )
    print_response(response)

    assert_field_extracted(response, "businessName", test_name)
    assert_field_extracted(response, "budget", test_name)
    assert_field_extracted(response, "websiteURL", test_name)
    assert_field_extracted(response, "durationDays", test_name)

    client.end_session()


# CATEGORY 3: STEP-BY-STEP INPUT


def test_step_by_step_flow():
    test_name = "Step-by-Step Flow"
    print_test_name(test_name)

    client = ChatV2TestClient()
    client.start_session()

    print_step(1, "Send: 'My business is Urban Fitness'")
    response = client.send_message("My business is Urban Fitness")
    print_response(response)
    assert_field_extracted(response, "businessName", test_name)
    assert_reply_not_empty(response, test_name)

    print_step(2, "Send: 'urbanfitness.com'")
    response = client.send_message("urbanfitness.com")
    print_response(response)
    assert_field_extracted(response, "websiteURL", test_name)
    assert_reply_not_empty(response, test_name)

    print_step(3, "Send: '7500'")
    response = client.send_message("7500")
    print_response(response)
    assert_field_extracted(response, "budget", test_name)
    assert_reply_not_empty(response, test_name)

    print_step(4, "Send: '14 days'")
    response = client.send_message("14 days")
    print_response(response)
    assert_field_extracted(response, "durationDays", test_name)

    client.end_session()


def test_random_order():
    """Test fields provided in random order"""
    test_name = "Random Order"
    print_test_name(test_name)

    client = ChatV2TestClient()
    client.start_session()

    print_step(1, "Budget first")
    response = client.send_message("My budget is 20000")
    assert_field_extracted(response, "budget", test_name)
    assert_reply_not_empty(response, test_name)

    print_step(2, "Duration second")
    response = client.send_message("For 10 days")
    assert_field_extracted(response, "durationDays", test_name)
    assert_reply_not_empty(response, test_name)

    print_step(3, "Website third")
    response = client.send_message("Website: techsolutions.io")
    assert_field_extracted(response, "websiteURL", test_name)
    assert_reply_not_empty(response, test_name)

    print_step(4, "Business name last")
    response = client.send_message("Business name is Tech Solutions")
    assert_field_extracted(response, "businessName", test_name)

    client.end_session()


def test_user_provides_different_field():
    """CRITICAL: When AI asks for business name but user provides budget, should acknowledge and continue"""
    test_name = "User Provides Different Field (Critical)"
    print_test_name(test_name)

    client = ChatV2TestClient()
    client.start_session()

    print_step(1, "Send greeting to start")
    response = client.send_message("Hi, I want to create a campaign")
    print_response(response)
    assert_reply_not_empty(response, test_name)

    print_step(2, "AI asked for business name, but send budget instead")
    response = client.send_message("my budget is 5k")
    print_response(response)

    # CRITICAL: Reply should NOT be empty
    assert_reply_not_empty(response, test_name)
    assert_field_extracted(response, "budget", test_name)

    client.end_session()


# CATEGORY 4: INPUT NORMALIZATION


def test_budget_normalization():
    """Test that various budget formats are accepted and extracted"""
    test_name = "Budget Normalization"
    print_test_name(test_name)

    test_cases = ["5k", "10K", "2.5k", "$5000", "15000"]

    for input_val in test_cases:
        client = ChatV2TestClient()
        client.start_session()

        print_step(1, f"Testing budget: {input_val}")
        response = client.send_message(f"budget is {input_val}")

        # Just verify budget was extracted (actual value normalization happens internally)
        assert_field_extracted(response, "budget", f"{test_name} ({input_val})")
        assert_reply_not_empty(response, f"{test_name} ({input_val})")

        client.end_session()
        time.sleep(0.3)


def test_url_normalization():
    """Test that various URL formats are accepted and extracted"""
    test_name = "URL Normalization"
    print_test_name(test_name)

    test_cases = ["google.com", "www.google.com", "https://google.com"]

    for input_val in test_cases:
        client = ChatV2TestClient()
        client.start_session()

        print_step(1, f"Testing URL: {input_val}")
        response = client.send_message(f"My website is {input_val}")

        # Just verify URL was extracted (actual normalization happens internally)
        assert_field_extracted(response, "websiteURL", f"{test_name} ({input_val})")
        assert_reply_not_empty(response, f"{test_name} ({input_val})")

        client.end_session()
        time.sleep(0.3)


# CATEGORY 5: VALIDATION & ERROR HANDLING


def test_invalid_url():
    test_name = "Invalid URL"
    print_test_name(test_name)

    client = ChatV2TestClient()
    client.start_session()

    print_step(1, "Send invalid URL: 'not-a-valid-url@@@'")
    response = client.send_message("My site is not-a-valid-url@@@")
    print_response(response)

    collected = response.get("collected_data") or {}
    stats.total += 1
    if "websiteURL" not in collected:
        print_success("Invalid URL not extracted")
        stats.passed += 1
    else:
        print_error("Invalid URL was extracted (should not be)")
        stats.failed += 1
        stats.failed_tests.append(test_name)

    assert_reply_not_empty(response, test_name)

    client.end_session()


def test_non_existent_domain():
    test_name = "Non-Existent Domain"
    print_test_name(test_name)

    client = ChatV2TestClient()
    client.start_session()

    print_step(1, "Send non-existent domain: 'svdgsvfgdsvfg.com'")
    response = client.send_message("My website is svdgsvfgdsvfg.com")
    print_response(response)

    collected = response.get("collected_data") or {}
    stats.total += 1
    if "websiteURL" not in collected:
        print_success("Non-existent domain correctly rejected")
        stats.passed += 1
    else:
        print_error("Non-existent domain was accepted")
        stats.failed += 1
        stats.failed_tests.append(test_name)

    client.end_session()


def test_valid_domain():
    test_name = "Valid Domain"
    print_test_name(test_name)

    client = ChatV2TestClient()
    client.start_session()

    print_step(1, "Send valid domain: 'https://www.google.com'")
    response = client.send_message("My website is https://www.google.com")
    print_response(response)

    assert_field_extracted(response, "websiteURL", test_name)

    client.end_session()


# CATEGORY 6: EDGE CASES


def test_unrelated_query():
    test_name = "Unrelated Query"
    print_test_name(test_name)

    client = ChatV2TestClient()
    client.start_session()

    print_step(1, "Send unrelated query")
    response = client.send_message("What's the weather today?")
    print_response(response)

    assert_reply_not_empty(response, test_name)

    # No fields should be extracted
    collected = response.get("collected_data") or {}
    stats.total += 1
    if not collected or len(collected) == 0:
        print_success("No fields extracted from unrelated query")
        stats.passed += 1
    else:
        print_error(f"Fields extracted from unrelated query: {collected}")
        stats.failed += 1
        stats.failed_tests.append(test_name)

    client.end_session()


def test_mixed_valid_invalid():
    test_name = "Mixed Valid and Invalid"
    print_test_name(test_name)

    client = ChatV2TestClient()
    client.start_session()

    print_step(1, "Send: 'Business is FitZone, mysite,com, 6k, 2 weeks'")
    response = client.send_message("Business is FitZone, mysite,com, 6k, 2 weeks")
    print_response(response)

    collected = response.get("collected_data") or {}

    stats.total += 3
    if "businessName" in collected:
        print_success("businessName extracted")
        stats.passed += 1
    else:
        print_error("businessName not extracted")
        stats.failed += 1
        stats.failed_tests.append(test_name)

    if "budget" in collected:
        print_success("budget extracted")
        stats.passed += 1
    else:
        print_error("budget not extracted")
        stats.failed += 1
        stats.failed_tests.append(test_name)

    if "websiteURL" not in collected:
        print_success("Invalid URL correctly rejected")
        stats.passed += 1
    else:
        print_error("Invalid URL was accepted")
        stats.failed += 1
        stats.failed_tests.append(test_name)

    client.end_session()


def test_empty_input():
    test_name = "Empty Input"
    print_test_name(test_name)

    client = ChatV2TestClient()
    client.start_session()

    print_step(1, "Send empty message")
    response = client.send_message("   ")
    print_response(response)

    stats.total += 1
    if response.get("status") in ["in_progress", "error"]:
        print_success("Empty input handled gracefully")
        stats.passed += 1
    else:
        print_error(f"Unexpected status for empty input: {response.get('status')}")
        stats.failed += 1
        stats.failed_tests.append(test_name)

    client.end_session()


def test_long_business_name():
    test_name = "Long Business Name"
    print_test_name(test_name)

    client = ChatV2TestClient()
    client.start_session()

    long_name = "The International Corporation for Advanced Technology Solutions and Digital Marketing Services"

    print_step(1, f"Send long business name ({len(long_name)} chars)")
    response = client.send_message(f"Business name is {long_name}")
    print_response(response)

    # Verify field was extracted and reply mentions the name
    assert_field_extracted(response, "businessName", test_name)
    assert_contains(response.get("reply", ""), "International", "Reply contains business name", test_name)

    client.end_session()


def test_special_characters():
    test_name = "Special Characters"
    print_test_name(test_name)

    client = ChatV2TestClient()
    client.start_session()

    special_name = "Joe's Cafe & Bakery"

    print_step(1, "Send business name with special characters")
    response = client.send_message(f"Business is {special_name}")
    print_response(response)

    # Verify field was extracted and reply mentions the name
    assert_field_extracted(response, "businessName", test_name)
    assert_contains(response.get("reply", ""), "Joe", "Reply contains business name", test_name)

    client.end_session()


# CATEGORY 7: SESSION MANAGEMENT


def test_invalid_session():
    test_name = "Invalid Session"
    print_test_name(test_name)

    client = ChatV2TestClient()
    client.session_id = "invalid-session-id-12345"

    print_step(1, "Send message with invalid session")
    response = client.send_message("hi")
    print_response(response)

    stats.total += 1
    if "error" in str(response).lower() or "invalid" in str(response).lower() or response.get("detail"):
        print_success("Invalid session rejected correctly")
        stats.passed += 1
    else:
        print_error(f"Invalid session not handled: {response}")
        stats.failed += 1
        stats.failed_tests.append(test_name)


def test_session_persistence():
    test_name = "Session Persistence"
    print_test_name(test_name)

    client = ChatV2TestClient()
    client.start_session()

    print_step(1, "Send business name")
    response = client.send_message("Business is PersistCo")
    assert_field_extracted(response, "businessName", test_name)

    print_step(2, "Send website (should remember business name)")
    response = client.send_message("Website is persistco.com")
    collected = response.get("collected_data") or {}

    stats.total += 1
    if "businessName" in collected and "websiteURL" in collected:
        print_success("Session persisted both fields")
        stats.passed += 1
    else:
        print_error(f"Session didn't persist fields: {collected}")
        stats.failed += 1
        stats.failed_tests.append(test_name)

    client.end_session()


# CATEGORY 8: END-TO-END FLOWS


def test_e2e_step_by_step():
    test_name = "E2E Step by Step"
    print_test_name(test_name)

    client = ChatV2TestClient()

    print_step(1, "Start session")
    client.start_session()

    print_step(2, "Greeting")
    response = client.send_message("hi")
    assert_reply_not_empty(response, test_name)

    print_step(3, "Business name")
    response = client.send_message("My business is StyleCo")
    assert_field_extracted(response, "businessName", test_name)
    assert_reply_not_empty(response, test_name)

    print_step(4, "Website")
    response = client.send_message("styleco.com")
    assert_field_extracted(response, "websiteURL", test_name)
    assert_reply_not_empty(response, test_name)

    print_step(5, "Budget")
    response = client.send_message("5k budget")
    assert_field_extracted(response, "budget", test_name)
    assert_reply_not_empty(response, test_name)

    print_step(6, "Duration")
    response = client.send_message("2 weeks")
    assert_field_extracted(response, "durationDays", test_name)

    print_step(7, "End session")
    client.end_session()


def test_e2e_all_at_once():
    test_name = "E2E All at Once"
    print_test_name(test_name)

    client = ChatV2TestClient()

    print_step(1, "Start session")
    client.start_session()

    print_step(2, "Provide all details")
    response = client.send_message(
        "I run TechHub, techhub.io, 10000 budget, 1 week"
    )
    print_response(response)

    assert_field_extracted(response, "businessName", test_name)
    assert_field_extracted(response, "websiteURL", test_name)
    assert_field_extracted(response, "budget", test_name)
    assert_field_extracted(response, "durationDays", test_name)

    print_step(3, "End session")
    client.end_session()


# TEST RUNNER


def run_all_tests():
    print_header("CHATV2 ASSISTANT - AUTOMATED TEST SUITE")
    print(f"{Fore.WHITE}Testing API at: {BASE_URL}{Style.RESET_ALL}")
    print(f"{Fore.WHITE}Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{Style.RESET_ALL}\n")

    try:
        # Category 1: Greetings
        print_header("CATEGORY 1: GREETING TESTS")
        test_simple_greeting()
        test_greeting_with_details()

        # Category 2: All-at-once
        print_header("CATEGORY 2: ALL-AT-ONCE INPUT")
        test_all_at_once_standard()
        test_all_at_once_informal()

        # Category 3: Step-by-step
        print_header("CATEGORY 3: STEP-BY-STEP INPUT")
        test_step_by_step_flow()
        test_random_order()
        test_user_provides_different_field()

        # Category 4: Normalization
        print_header("CATEGORY 4: INPUT NORMALIZATION")
        test_budget_normalization()
        test_url_normalization()

        # Category 5: Validation
        print_header("CATEGORY 5: VALIDATION & ERROR HANDLING")
        test_invalid_url()
        test_non_existent_domain()
        test_valid_domain()

        # Category 6: Edge cases
        print_header("CATEGORY 6: EDGE CASES")
        test_unrelated_query()
        test_mixed_valid_invalid()
        test_empty_input()
        test_long_business_name()
        test_special_characters()

        # Category 7: Session management
        print_header("CATEGORY 7: SESSION MANAGEMENT")
        test_invalid_session()
        test_session_persistence()

        # Category 8: End-to-end
        print_header("CATEGORY 8: END-TO-END FLOWS")
        test_e2e_step_by_step()
        test_e2e_all_at_once()

    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}Tests interrupted by user{Style.RESET_ALL}")
    except Exception as e:
        print(f"\n{Fore.RED}Fatal error: {e}{Style.RESET_ALL}")
        import traceback
        traceback.print_exc()

    # Print summary
    print_header("TEST SUMMARY")

    total = stats.total
    passed = stats.passed
    failed = stats.failed
    pass_rate = (passed / total * 100) if total > 0 else 0

    print(f"\n{Fore.WHITE}Total Assertions: {total}{Style.RESET_ALL}")
    print(f"{Fore.GREEN}Passed: {passed} ({pass_rate:.1f}%){Style.RESET_ALL}")
    print(f"{Fore.RED}Failed: {failed} ({100-pass_rate:.1f}%){Style.RESET_ALL}")

    if stats.failed_tests:
        print(f"\n{Fore.RED}Failed Tests:{Style.RESET_ALL}")
        for test in set(stats.failed_tests):
            print(f"  {Fore.RED}x {test}{Style.RESET_ALL}")

    print(f"\n{Fore.WHITE}End time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{Style.RESET_ALL}")

    if failed == 0:
        print(f"\n{Fore.GREEN}{'='*80}")
        print(f"{Fore.GREEN}ALL TESTS PASSED!{Style.RESET_ALL}")
        print(f"{Fore.GREEN}{'='*80}{Style.RESET_ALL}\n")
        return 0
    else:
        print(f"\n{Fore.RED}{'='*80}")
        print(f"{Fore.RED}SOME TESTS FAILED!{Style.RESET_ALL}")
        print(f"{Fore.RED}{'='*80}{Style.RESET_ALL}\n")
        return 1


if __name__ == "__main__":
    import sys
    exit_code = run_all_tests()
    sys.exit(exit_code)
