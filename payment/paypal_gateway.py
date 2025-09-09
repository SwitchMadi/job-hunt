import os
import requests
from typing import Dict, Any
from . import PaymentGatewayInterface, PaymentResult
from utilities.logging import get_logger

logger = get_logger(name="paypal_gateway")


class PayPalGateway(PaymentGatewayInterface):
    """
    PayPal implementation of PaymentGatewayInterface.
    """

    def __init__(self):
        self.client_id = os.getenv("PAYPAL_CLIENT_ID")
        self.client_secret = os.getenv("PAYPAL_CLIENT_SECRET")
        self.webhook_id = os.getenv("PAYPAL_WEBHOOK_ID")
        self.environment = os.getenv("PAYPAL_ENVIRONMENT", "sandbox")
        self.base_url = (
            "https://api-m.sandbox.paypal.com"
            if self.environment == "sandbox"
            else "https://api-m.paypal.com"
        )

        # Current order data (shared between methods in same operation)
        self._current_order = None

    def create_order(
        self, amount: float, currency: str, user_email: str, description: str
    ) -> PaymentResult:
        """
        Create a PayPal order.
        """
        try:
            # Get access token
            access_token = self._get_access_token()
            if not access_token:
                return PaymentResult(
                    payment_id="",
                    status="failed",
                    amount=amount,
                    currency=currency,
                    user_email=user_email,
                    gateway="paypal",
                    error_message="Failed to get PayPal access token",
                )

            # Create order payload
            order_payload = {
                "intent": "CAPTURE",
                "purchase_units": [
                    {
                        "amount": {"currency_code": currency, "value": str(amount)},
                        "custom_id": user_email,
                        "description": description,
                    }
                ],
                "payer": {"email_address": user_email},
                "application_context": {
                    "return_url": "https://switchmadi.com/free-job-application?payment=success",
                    "cancel_url": "https://switchmadi.com/free-job-application?payment=cancelled",
                    "brand_name": "SwitchMadi",
                    "landing_page": "BILLING",
                    "user_action": "PAY_NOW",
                },
            }

            # Make API call
            response = requests.post(
                f"{self.base_url}/v2/checkout/orders",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                },
                json=order_payload,
                timeout=30,
            )

            if response.status_code == 201:
                order_data = response.json()
                return PaymentResult(
                    payment_id=order_data["id"],
                    status="pending",
                    amount=amount,
                    currency=currency,
                    user_email=user_email,
                    gateway="paypal",
                    order_id=order_data["id"],
                )
            else:
                logger.error(
                    f"PayPal order creation failed: {response.status_code} - {response.text}"
                )
                return PaymentResult(
                    payment_id="",
                    status="failed",
                    amount=amount,
                    currency=currency,
                    user_email=user_email,
                    gateway="paypal",
                    error_message=f"Order creation failed: {response.text}",
                )

        except Exception as e:
            logger.exception(f"Error creating PayPal order: {e}")
            return PaymentResult(
                payment_id="",
                status="failed",
                amount=amount,
                currency=currency,
                user_email=user_email,
                gateway="paypal",
                error_message=str(e),
            )

    def handle_webhook(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> PaymentResult:
        """
        Handle PayPal webhook.
        """
        try:
            # Verify webhook first
            if not self.verify_webhook(payload, headers):
                logger.warning("PayPal webhook verification failed")
                return PaymentResult(
                    payment_id="",
                    status="failed",
                    amount=0,
                    currency="USD",
                    user_email="",
                    gateway="paypal",
                    error_message="Webhook verification failed",
                )

            # Process webhook based on event type
            event_type = payload.get("event_type", "")

            if event_type == "PAYMENT.CAPTURE.COMPLETED":
                return self._handle_payment_completed(payload)
            elif event_type == "PAYMENT.CAPTURE.DENIED":
                return self._handle_payment_denied(payload)
            else:
                logger.info(f"Unhandled PayPal webhook event: {event_type}")
                return PaymentResult(
                    payment_id="",
                    status="ignored",
                    amount=0,
                    currency="USD",
                    user_email="",
                    gateway="paypal",
                )

        except Exception as e:
            logger.exception(f"Error handling PayPal webhook: {e}")
            return PaymentResult(
                payment_id="",
                status="failed",
                amount=0,
                currency="USD",
                user_email="",
                gateway="paypal",
                error_message=str(e),
            )

    def verify_webhook(self, payload: Dict[str, Any], headers: Dict[str, str]) -> bool:
        """
        Verify PayPal webhook signature.
        """
        try:
            # Get required headers
            paypal_transmission_id = headers.get("PAYPAL-TRANSMISSION-ID", "")
            paypal_cert_url = headers.get("PAYPAL-CERT-URL", "")
            paypal_transmission_sig = headers.get("PAYPAL-TRANSMISSION-SIG", "")
            paypal_transmission_time = headers.get("PAYPAL-TRANSMISSION-TIME", "")
            paypal_auth_algo = headers.get("PAYPAL-AUTH-ALGO", "")

            # Check if all required headers are present
            if not all(
                [
                    paypal_transmission_id,
                    paypal_cert_url,
                    paypal_transmission_sig,
                    paypal_transmission_time,
                    paypal_auth_algo,
                ]
            ):
                logger.warning(
                    "Missing required PayPal webhook headers for verification"
                )
                return False

            # Prepare verification payload
            verification_payload = {
                "auth_algo": paypal_auth_algo,
                "cert_url": paypal_cert_url,
                "transmission_id": paypal_transmission_id,
                "transmission_sig": paypal_transmission_sig,
                "transmission_time": paypal_transmission_time,
                "webhook_id": self.webhook_id,
                "webhook_event": payload,
            }

            # Get access token for verification
            access_token = self._get_access_token()
            if not access_token:
                logger.error(
                    "Failed to get PayPal access token for webhook verification"
                )
                return False

            # Call PayPal's verification endpoint
            response = requests.post(
                f"{self.base_url}/v1/notifications/verify-webhook-signature",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                },
                json=verification_payload,
                timeout=30,
            )

            if response.status_code == 200:
                verification_result = response.json()
                verification_status = verification_result.get("verification_status")

                if verification_status == "SUCCESS":
                    logger.info("PayPal webhook signature verification successful")
                    return True
                else:
                    logger.warning(
                        f"PayPal webhook signature verification failed: {verification_status}"
                    )
                    return False
            else:
                logger.error(
                    f"PayPal verification endpoint returned status {response.status_code}: {response.text}"
                )
                return False

        except Exception as e:
            logger.exception(f"Error verifying PayPal webhook signature: {e}")
            return False

    def _get_order_details(self, order_id: str) -> dict:
        """
        Get order details from PayPal API.
        Returns current order data if available, otherwise fetches from PayPal.
        """
        try:
            # Check if we already have order data for this operation
            if self._current_order and self._current_order.get("id") == order_id:
                logger.info(
                    f"Order {order_id} details already available from current operation"
                )
                return self._current_order

            # Fetch from PayPal if not available
            logger.info(f"Fetching order {order_id} details from PayPal")

            # Get access token
            access_token = self._get_access_token()
            if not access_token:
                logger.error("Failed to get PayPal access token for order details")
                return {}

            # Get order details from PayPal
            response = requests.get(
                f"{self.base_url}/v2/checkout/orders/{order_id}",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                },
                timeout=30,
            )

            if response.status_code == 200:
                order_data = response.json()
                logger.info(f"Order {order_id} details fetched successfully")
                return order_data
            else:
                logger.error(
                    f"Failed to get order details: {response.status_code} - {response.text}"
                )
                return {}

        except Exception as e:
            logger.exception(f"Error getting order details: {e}")
            return {}

    def verify_order_ownership(self, order_id: str, user_email: str) -> bool:
        """
        Verify that an order belongs to the specified user.
        Uses current order data if available.
        """
        try:
            # Get order details (will use current order if available)
            order_data = self._get_order_details(order_id)

            if not order_data:
                logger.error(f"Failed to get order details for {order_id}")
                return False

            # Check if order exists and get custom_id (user email)
            purchase_units = order_data.get("purchase_units", [])
            if purchase_units:
                custom_id = purchase_units[0].get("custom_id", "")
                is_owner = custom_id == user_email

                if is_owner:
                    logger.info(f"Order {order_id} verified for user {user_email}")
                else:
                    logger.warning(
                        f"Order {order_id} custom_id ({custom_id}) does not match user email ({user_email})"
                    )

                return is_owner

            logger.warning(f"No purchase units found in order {order_id}")
            return False

        except Exception as e:
            logger.exception(f"Error verifying order ownership: {e}")
            return False

    def capture_order(self, order_id: str) -> PaymentResult:
        """
        Capture a PayPal order.
        This method will store the order details for other methods to use.
        """
        try:
            # Get access token
            access_token = self._get_access_token()
            if not access_token:
                return PaymentResult(
                    payment_id="",
                    status="failed",
                    amount=0,
                    currency="USD",
                    user_email="",
                    gateway="paypal",
                    error_message="Failed to get PayPal access token",
                )

            # Make capture API call
            response = requests.post(
                f"{self.base_url}/v2/checkout/orders/{order_id}/capture",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                },
                json={},  # Empty body for capture
                timeout=30,
            )

            if response.status_code == 201:
                order_data = response.json()

                # Store the order data for other methods to use
                self._current_order = order_data
                logger.info(f"Order {order_id} details stored for current operation")

                # Extract capture details
                purchase_units = order_data.get("purchase_units", [])
                if purchase_units:
                    payments = purchase_units[0].get("payments", {})
                    captures = payments.get("captures", [])
                    if captures:
                        capture = captures[0]
                        amount = float(capture.get("amount", {}).get("value", "0"))
                        currency = capture.get("amount", {}).get("currency_code", "USD")
                        payment_id = capture.get("id", "")
                        status = capture.get("status", "")

                        return PaymentResult(
                            payment_id=payment_id,
                            status="completed" if status == "COMPLETED" else "failed",
                            amount=amount,
                            currency=currency,
                            user_email="",  # Will be filled by caller
                            gateway="paypal",
                            order_id=order_id,
                        )

                # Fallback if no capture found
                return PaymentResult(
                    payment_id="",
                    status="failed",
                    amount=0,
                    currency="USD",
                    user_email="",
                    gateway="paypal",
                    error_message="No capture found in response",
                )
            else:
                logger.error(
                    f"PayPal order capture failed: {response.status_code} - {response.text}"
                )
                return PaymentResult(
                    payment_id="",
                    status="failed",
                    amount=0,
                    currency="USD",
                    user_email="",
                    gateway="paypal",
                    error_message=f"Order capture failed: {response.text}",
                )

        except Exception as e:
            logger.exception(f"Error capturing PayPal order: {e}")
            return PaymentResult(
                payment_id="",
                status="failed",
                amount=0,
                currency="USD",
                user_email="",
                gateway="paypal",
                error_message=str(e),
            )

    def get_client_config(self) -> Dict[str, Any]:
        """
        Get PayPal client configuration for frontend.
        """
        return {
            "client_id": self.client_id,
            "environment": self.environment,
            "currency": "USD",
        }

    def _get_access_token(self) -> str:
        """
        Get PayPal access token.
        """
        try:
            response = requests.post(
                f"{self.base_url}/v1/oauth2/token",
                headers={"Accept": "application/json", "Accept-Language": "en_US"},
                auth=(self.client_id, self.client_secret),
                data="grant_type=client_credentials",
                timeout=30,
            )

            if response.status_code == 200:
                token_data = response.json()
                return token_data.get("access_token")
            else:
                logger.error(
                    f"Failed to get PayPal access token: {response.status_code} - {response.text}"
                )
                return None

        except Exception as e:
            logger.exception(f"Error getting PayPal access token: {e}")
            return None

    def _handle_payment_completed(self, payload: Dict[str, Any]) -> PaymentResult:
        """
        Handle payment completed webhook.
        """
        try:
            resource = payload.get("resource", {})
            custom_id = resource.get("custom_id", "")
            amount = float(resource.get("amount", {}).get("value", "0"))
            currency = resource.get("amount", {}).get("currency_code", "USD")
            payment_id = resource.get("id", "")

            return PaymentResult(
                payment_id=payment_id,
                status="completed",
                amount=amount,
                currency=currency,
                user_email=custom_id,
                gateway="paypal",
            )

        except Exception as e:
            logger.exception(f"Error handling payment completed: {e}")
            return PaymentResult(
                payment_id="",
                status="failed",
                amount=0,
                currency="USD",
                user_email="",
                gateway="paypal",
                error_message=str(e),
            )

    def _handle_payment_denied(self, payload: Dict[str, Any]) -> PaymentResult:
        """
        Handle payment denied webhook.
        """
        try:
            resource = payload.get("resource", {})
            custom_id = resource.get("custom_id", "")
            amount = float(resource.get("amount", {}).get("value", "0"))
            currency = resource.get("amount", {}).get("currency_code", "USD")
            payment_id = resource.get("id", "")

            return PaymentResult(
                payment_id=payment_id,
                status="failed",
                amount=amount,
                currency=currency,
                user_email=custom_id,
                gateway="paypal",
                error_message="Payment was denied",
            )

        except Exception as e:
            logger.exception(f"Error handling payment denied: {e}")
            return PaymentResult(
                payment_id="",
                status="failed",
                amount=0,
                currency="USD",
                user_email="",
                gateway="paypal",
                error_message=str(e),
            )
