from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class PaymentResult:
    """
    Standardized payment result object.
    """

    payment_id: str
    status: str  # "completed", "failed", "pending"
    amount: float
    currency: str
    user_email: str
    gateway: str  # "paypal", "stripe", etc.
    order_id: str = None
    error_message: str = None


class PaymentGatewayInterface(ABC):
    """
    Abstract interface for payment gateway implementations.
    """

    @abstractmethod
    def create_order(
        self, amount: float, currency: str, user_email: str, description: str
    ) -> PaymentResult:
        """
        Create a payment order.

        Args:
            amount: Payment amount
            currency: Currency code (e.g., 'USD')
            user_email: User's email address
            description: Payment description

        Returns:
            PaymentResult: Order creation result
        """
        pass

    @abstractmethod
    def handle_webhook(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> PaymentResult:
        """
        Handle incoming webhook from payment gateway.

        Args:
            payload: Webhook payload data
            headers: Webhook headers

        Returns:
            PaymentResult: Webhook processing result
        """
        pass

    @abstractmethod
    def verify_webhook(self, payload: Dict[str, Any], headers: Dict[str, str]) -> bool:
        """
        Verify webhook authenticity.

        Args:
            payload: Webhook payload data
            headers: Webhook headers

        Returns:
            bool: True if webhook is authentic
        """
        pass

    @abstractmethod
    def get_client_config(self) -> Dict[str, Any]:
        """
        Get client configuration for frontend SDK.

        Returns:
            Dict: Configuration for frontend payment SDK
        """
        pass


class PaymentGatewayFactory:
    """
    Factory class for creating payment gateway instances.
    """

    @staticmethod
    def create_gateway(gateway_type: str) -> Optional[PaymentGatewayInterface]:
        """
        Create a payment gateway instance based on the gateway type.

        Args:
            gateway_type: Type of payment gateway ("paypal", "stripe", etc.)

        Returns:
            PaymentGatewayInterface instance or None if not supported
        """
        try:
            if gateway_type.lower() == "paypal":
                from .paypal_gateway import PayPalGateway

                return PayPalGateway()
            elif gateway_type.lower() == "stripe":
                # Future implementation
                # from .stripe_gateway import StripeGateway
                # return StripeGateway()
                raise NotImplementedError("Stripe gateway not yet implemented")
            elif gateway_type.lower() == "razorpay":
                # Future implementation
                # from .razorpay_gateway import RazorpayGateway
                # return RazorpayGateway()
                raise NotImplementedError("Razorpay gateway not yet implemented")
            else:
                raise ValueError(f"Unsupported payment gateway: {gateway_type}")

        except Exception as e:
            from utilities.logging import get_logger

            logger = get_logger(name="payment_factory")
            logger.error(f"Failed to create payment gateway '{gateway_type}': {e}")
            return None

    @staticmethod
    def get_available_gateways() -> list:
        """
        Get list of available payment gateways.

        Returns:
            List of supported gateway types
        """
        return ["paypal"]  # Add more as they're implemented
