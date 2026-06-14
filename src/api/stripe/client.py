import os
import logging
from typing import Dict, Any, Tuple, Optional
import stripe

from api.db.subscription_plans import SubscriptionPlanDB

# Configure logging
logger = logging.getLogger(__name__)

class StripeClient:
    def __init__(self):
        self.stripe_api_key = os.getenv('STRIPE_API_KEY', '').strip('"')
        self.webhook_secret = os.getenv('STRIPE_WEBHOOK_SECRET', '').strip('"')
        self.frontend_url = os.getenv('FRONTEND_URL', '').strip('"')
        # Optional: explicitly specify a Billing Portal configuration to use
        self.billing_portal_configuration_id = os.getenv('STRIPE_BILLING_PORTAL_CONFIGURATION_ID', '').strip('"')
        
        if not self.stripe_api_key:
            raise ValueError("STRIPE_API_KEY environment variable is not set")
        
        if not self.webhook_secret:
            raise ValueError("STRIPE_WEBHOOK_SECRET environment variable is not set")
            
        if not self.frontend_url:
            raise ValueError("FRONTEND_URL environment variable is not set")
        
    # TODO: this functino must be removed and use a function from mongo directly
    def _update_user_stripe_customer_id(self, user_email: str, stripe_customer_id: str):
        """Update user record with Stripe customer ID"""
        try:
            from api.db.users import UserDB
            user_db = UserDB()
            user_db.update_user_stripe_customer_id(user_email, stripe_customer_id)
            logger.info(f"Updated user {user_email} with Stripe customer ID {stripe_customer_id}")
        except Exception as e:
            logger.error(f"Failed to update user {user_email} with Stripe customer ID: {str(e)}")
        
    def create_customer(self, email: str, metadata: Optional[Dict[str, Any]] = None) -> stripe.Customer:
        """Create a new Stripe customer"""
        try:
            customer = stripe.Customer.create(
                email=email,
                metadata=metadata or {},
                api_key=self.stripe_api_key
            )
            return customer
        except stripe.error.CardError as e:
            # Card was declined
            logger.error(f"Card error creating customer: {str(e)}")
            raise Exception(f"Card declined: {e.user_message}")
        except stripe.error.RateLimitError as e:
            # Too many requests
            logger.error(f"Rate limit error creating customer: {str(e)}")
            raise Exception("Too many requests. Please try again in a moment.")
        except stripe.error.InvalidRequestError as e:
            # Invalid parameters
            logger.error(f"Invalid request creating customer: {str(e)}")
            raise Exception(f"Invalid request: {e.user_message}")
        except stripe.error.AuthenticationError as e:
            # Authentication failed
            logger.error(f"Authentication error creating customer: {str(e)}")
            raise Exception("Payment system configuration error. Please contact support.")
        except stripe.error.APIConnectionError as e:
            # Network communication failed
            logger.error(f"Network error creating customer: {str(e)}")
            raise Exception("Network error. Please check your connection and try again.")
        except stripe.error.StripeError as e:
            # Generic Stripe error
            logger.error(f"Stripe error creating customer: {str(e)}")
            raise Exception("Unable to create customer account. Please try again.")
        except Exception as e:
            logger.error(f"Unexpected error creating customer: {str(e)}")
            raise Exception("Service temporarily unavailable")
    
    def create_checkout_session(self, 
                              price_id: str, 
                              user_email: str,
                              user_id: str,
                              success_url: Optional[str] = None,
                              cancel_url: Optional[str] = None,
                              stripe_customer_id: Optional[str] = None) -> Tuple[Dict[str, Any], int]:
        """Create a Stripe checkout session for subscription"""
        try:
            # Use provided customer ID if available, otherwise create new customer
            if stripe_customer_id:
                customer_id = stripe_customer_id
            else:
                # Create new customer for first subscription
                customer = self.create_customer(
                    email=user_email,
                    metadata={'user_id': user_id, 'source': 'first_subscription'}
                )
                customer_id = customer.id
                
                # Update user record with new Stripe customer ID
                self._update_user_stripe_customer_id(user_email, customer_id)
                logger.info(f"Created Stripe customer {customer_id} for first subscription by {user_email}")
            
            # Create checkout session
            session = stripe.checkout.Session.create(
                customer=customer_id,
                payment_method_types=['card'],
                line_items=[{
                    'price': price_id,
                    'quantity': 1,
                }],
                mode='subscription',
                success_url=success_url or f"{self.frontend_url.replace('dashboard.', 'api.')}/stripe/success?session_id={{CHECKOUT_SESSION_ID}}",
                cancel_url=cancel_url or f"{self.frontend_url}/cancel",
                metadata={
                    'user_id': user_id
                },
                api_key=self.stripe_api_key
            )
            
            return {
                'checkout_url': session.url,
                'session_id': session.id
            }, 200

        except stripe.error.CardError as e:
            # Card was declined
            logger.error(f"Card error creating checkout session: {str(e)}")
            return {'error': f'Card declined: {e.user_message}'}, 400
        except stripe.error.RateLimitError as e:
            # Too many requests
            logger.error(f"Rate limit error creating checkout session: {str(e)}")
            return {'error': 'Too many requests. Please try again in a moment.'}, 429
        except stripe.error.InvalidRequestError as e:
            # Invalid parameters
            logger.error(f"Invalid request creating checkout session: {str(e)}")
            return {'error': f'Invalid request: {e.user_message}'}, 400
        except stripe.error.AuthenticationError as e:
            # Authentication failed
            logger.error(f"Authentication error creating checkout session: {str(e)}")
            return {'error': 'Payment system configuration error. Please contact support.'}, 500
        except stripe.error.APIConnectionError as e:
            # Network communication failed
            logger.error(f"Network error creating checkout session: {str(e)}")
            return {'error': 'Network error. Please try again.'}, 503
        except stripe.error.StripeError as e:
            # Generic Stripe error
            logger.error(f"Stripe error creating checkout session: {str(e)}")
            return {'error': 'Payment processing temporarily unavailable'}, 400
        except Exception as e:
            logger.error(f"Unexpected error creating checkout session: {str(e)}")
            return {'error': 'Service temporarily unavailable'}, 500
    
    def handle_webhook_event(self, payload: bytes, sig_header: str) -> Tuple[Dict[str, Any], int]:
        """Handle Stripe webhook events"""
        try:
            def sync_subscription(email: Optional[str]):
                """Utility to trigger a centralized subscription sync."""
                if not email:
                    return
                try:
                    from api.db.users import UserDB
                    from api.stripe import sync_user_subscription

                    user_db = UserDB()
                    sync_user_subscription(email, user_db=user_db)
                except Exception as sync_error:
                    logger.error(f"Failed to sync subscription snapshot for {email}: {sync_error}")

            # Construct the event
            event = stripe.Webhook.construct_event(
                payload, sig_header, self.webhook_secret
            )
            
            # Handle different event types
            if event['type'] == 'payment_intent.succeeded':
                payment_intent = event['data']['object']
                logger.info(f"Payment intent succeeded: {payment_intent['id']}")
                
                # Check if this is a credit purchase
                metadata = payment_intent.get('metadata', {})
                payment_type = metadata.get('type')
                
                if payment_type == 'credit_purchase':
                    # Handle credit purchase
                    user_email = metadata.get('user_email')
                    credit_amount = float(metadata.get('credit_amount', 0))
                    
                    if user_email and credit_amount > 0:
                        try:
                            from api.db.users import UserDB
                            user_db = UserDB()
                            success = user_db.add_credits(user_email, credit_amount)
                            if success:
                                logger.info(f"Successfully added ${credit_amount:.2f} credits to user {user_email}")
                            else:
                                logger.error(f"Failed to add credits to user {user_email}")
                        except Exception as credit_error:
                            logger.error(f"Error adding credits to user {user_email}: {str(credit_error)}")
                            
            elif event['type'] == 'invoice.payment_succeeded':
                invoice = event['data']['object']
                logger.info(f"Invoice payment succeeded: {invoice['id']}")
                
                # Get customer email and subscription info from invoice
                customer_email = invoice.get('customer_email')
                subscription_id = None
                
                # Extract subscription ID from invoice parent details
                parent = invoice.get('parent', {})
                if parent.get('type') == 'subscription_details':
                    subscription_id = parent.get('subscription_details', {}).get('subscription')
                
                # Get amount from invoice (convert from cents to dollars based on currency)
                amount_paid = invoice.get('amount_paid', 0)
                currency = invoice.get('currency', 'usd')
                
                # Convert to dollars (assuming EUR and USD both use cents)
                subscription_amount = amount_paid / 100.0
                
                logger.info(f"---------_ Invoice payment - Customer: {customer_email}, Subscription: {subscription_id}, Amount: {subscription_amount} {currency.upper()}")
                
                if customer_email and subscription_id:
                    try:
                        logger.info(f"---------_ Starting subscription processing for user {customer_email} with subscription_id {subscription_id}")
                        
                        # Extract product ID from invoice line items (simpler approach)
                        lines = invoice.get('lines', {}).get('data', [])
                        if lines:
                            line_item = lines[0]
                            pricing = line_item.get('pricing', {})
                            price_details = pricing.get('price_details', {})
                            product_id = price_details.get('product')
                            
                            if product_id:
                                # Get product name
                                product_obj = stripe.Product.retrieve(product_id, api_key=self.stripe_api_key)
                                product_name = product_obj.name
                                logger.info(f"---------_ Retrieved product details from invoice: {product_name} (product_id: {product_id})")
                                
                                logger.info(f"---------_ Subscription amount: ${subscription_amount:.2f} {currency.upper()}")
                                
                                # Find user by email
                                from api.db.users import UserDB
                                user_db = UserDB()
                                
                                logger.info(f"---------_ User {customer_email} subscribed to {product_name} for ${subscription_amount:.2f}")
                                
                                # Add subscription amount to user's credit balance
                                logger.info(f"---------_ Adding ${subscription_amount:.2f} credits to user {customer_email} account")
                                success = user_db.add_credits(customer_email, subscription_amount)
                                if success:
                                    new_balance = user_db.get_credit_balance(customer_email)
                                    logger.info(f"---------_ ✅ Successfully added ${subscription_amount:.2f} credits to user {customer_email}. New balance: ${new_balance:.6f}")
                                else:
                                    logger.error(f"---------_ ❌ Failed to add credits to user {customer_email}")

                                sync_subscription(customer_email)
                            else:
                                logger.warning("---------_ No product ID found in invoice line items")
                        else:
                            logger.warning("---------_ No line items found in invoice")
                                
                    except Exception as sub_error:
                        logger.error(f"---------_ ❌ Error processing subscription for user {customer_email}: {str(sub_error)}")
                else:
                    logger.info("Invoice payment succeeded but missing customer_email or subscription_id")
                
            elif event['type'] == 'checkout.session.completed':
                session = event['data']['object']
                logger.info(f"Checkout session completed: {session['id']}")
                
                # Handle successful subscription
                customer_id = session.get('customer')
                subscription_id = session.get('subscription')
                metadata = session.get('metadata', {})
                user_id = metadata.get('user_id')
                
                if subscription_id:
                    try:
                        logger.info(f"---------_ Starting subscription processing for user {user_id} with subscription_id {subscription_id}")

                        # Get subscription details to find the product name and amount
                        subscription_obj = stripe.Subscription.retrieve(
                            subscription_id,
                            expand=['items.data.price'],
                            api_key=self.stripe_api_key
                        )
                        logger.info(f"---------_ Retrieved subscription object for {subscription_id}")

                        if subscription_obj and subscription_obj.items.data:
                            subscription_item = subscription_obj.items.data[0]
                            price_obj = subscription_item.price

                            # Get product name
                            product_obj = stripe.Product.retrieve(price_obj.product, api_key=self.stripe_api_key)
                            product_name = product_obj.name
                            logger.info(f"---------_ Retrieved product details: {product_name} (product_id: {price_obj.product})")
                            
                            # Get subscription amount (convert from cents to dollars)
                            subscription_amount = (price_obj.unit_amount or 0) / 100.0
                            logger.info(f"---------_ Subscription amount: ${subscription_amount:.2f} (from {price_obj.unit_amount} cents)")
                            
                            # Find user by email (user_id is the email)
                            from api.db.users import UserDB
                            user_db = UserDB()
                            
                            logger.info(f"---------_ User {user_id} subscribed to {product_name} for ${subscription_amount}")
                            
                            # Add subscription amount to user's credit balance
                            logger.info(f"---------_ Adding ${subscription_amount:.2f} credits to user {user_id} account")
                            success = user_db.add_credits(user_id, subscription_amount)
                            if success:
                                new_balance = user_db.get_credit_balance(user_id)
                                logger.info(f"---------_ ✅ Successfully added ${subscription_amount:.2f} credits to user {user_id}. New balance: ${new_balance:.6f}")
                            else:
                                logger.error(f"---------_ ❌ Failed to add credits to user {user_id}")

                            sync_subscription(user_id)
                                
                        else:
                            logger.warning(f"---------_ No subscription items found for subscription {subscription_id}")
                                
                    except Exception as sub_error:
                        logger.error(f"---------_ ❌ Error processing subscription for user {user_id}: {str(sub_error)}")
                else:
                    logger.info(f"User {user_id} completed checkout but no subscription found")
                
            elif event['type'] == 'customer.subscription.created':
                subscription = event['data']['object']
                logger.info(f"Subscription created: {subscription['id']}")
                
                # Handle new subscription creation
                customer_id = subscription.get('customer')
                subscription_status = subscription.get('status')
                
                if customer_id and subscription_status == 'active':
                    try:
                        logger.info(f"---------_ Processing new subscription {subscription['id']} for customer {customer_id}")

                        # Get customer details to find email
                        customer = stripe.Customer.retrieve(customer_id, api_key=self.stripe_api_key)
                        customer_email = customer.email
                        
                        if customer_email:
                            # Get subscription details
                            if subscription.get('items', {}).get('data'):
                                subscription_item = subscription['items']['data'][0]
                                price_obj = subscription_item.get('price')
                                
                                if price_obj:
                                    # Get product name
                                    product_obj = stripe.Product.retrieve(price_obj['product'], api_key=self.stripe_api_key)
                                    product_name = product_obj.name
                                    
                                    # Get subscription amount
                                    subscription_amount = (price_obj.get('unit_amount', 0)) / 100.0
                                    currency = price_obj.get('currency', 'eur')
                                    
                                    logger.info(f"---------_ New subscription details: {product_name} for {customer_email} - ${subscription_amount:.2f} {currency.upper()}")
                                    
                                    # Find user by email
                                    from api.db.users import UserDB
                                    user_db = UserDB()
                                    
                                    # Add subscription amount to user's credit balance
                                    logger.info(f"---------_ Adding ${subscription_amount:.2f} credits to user {customer_email} account")
                                    success = user_db.add_credits(customer_email, subscription_amount)
                                    if success:
                                        new_balance = user_db.get_credit_balance(customer_email)
                                        logger.info(f"---------_ ✅ Successfully added ${subscription_amount:.2f} credits to user {customer_email}. New balance: ${new_balance:.6f}")
                                    else:
                                        logger.error(f"---------_ ❌ Failed to add credits to user {customer_email}")

                                    sync_subscription(customer_email)
                        else:
                            logger.warning(f"---------_ No email found for customer {customer_id}")
                            
                    except Exception as sub_error:
                        logger.error(f"---------_ ❌ Error processing new subscription: {str(sub_error)}")
                        
            elif event['type'] == 'customer.subscription.deleted':
                subscription = event['data']['object']
                logger.info(f"Subscription cancelled: {subscription['id']}")
                
                customer_id = subscription.get('customer')
                email: Optional[str] = None
                if customer_id:
                    try:
                        customer = stripe.Customer.retrieve(customer_id, api_key=self.stripe_api_key)
                        email = getattr(customer, 'email', None)
                    except Exception as lookup_error:
                        logger.error(f"Failed to resolve customer email for cancellation {subscription['id']}: {lookup_error}")

                sync_subscription(email)

            elif event['type'] == 'customer.subscription.updated':
                subscription = event['data']['object']
                logger.info(f"Subscription updated: {subscription['id']}")
                
                customer_id = subscription.get('customer')
                email: Optional[str] = None
                if customer_id:
                    try:
                        customer = stripe.Customer.retrieve(customer_id, api_key=self.stripe_api_key)
                        email = getattr(customer, 'email', None)
                    except Exception as lookup_error:
                        logger.error(f"Failed to resolve customer email for subscription update {subscription['id']}: {lookup_error}")

                sync_subscription(email)

            else:
                logger.info(f"Unhandled event type: {event['type']}")
            
            return {'received': True}, 200
            
        except ValueError as e:
            # Invalid payload
            logger.error(f"Webhook invalid payload: {str(e)}")
            return {'error': 'Invalid request'}, 400
            
        except stripe.error.SignatureVerificationError as e:
            # Invalid signature
            logger.error(f"Webhook signature verification failed: {str(e)}")
            return {'error': 'Unauthorized request'}, 400
            
        except Exception as e:
            logger.error(f"Webhook handler error: {str(e)}")
            return {'error': 'Processing failed'}, 500
    
    def get_subscription_status(self, customer_email: str) -> Optional[Dict[str, Any]]:
        """Get the subscription status for a customer"""
        try:
            # Find customer by email
            customers = stripe.Customer.list(email=customer_email, limit=1, api_key=self.stripe_api_key)
            if not customers.data:
                logger.info(f"No customer found with email: {customer_email}")
                return None
            
            customer = customers.data[0]
            logger.info(f"Found customer: {customer.id}")

            # Get subscriptions for this customer (including all statuses to check the most recent one)
            subscriptions = stripe.Subscription.list(
                customer=customer.id,
                status='all',
                limit=10,  # Get recent subscriptions
                expand=['data.items.data.price'],  # Expand to include price data only
                api_key=self.stripe_api_key
            )
            
            if not subscriptions.data:
                logger.info(f"No subscriptions found for customer: {customer.id}")
                return {'status': 'inactive', 'customer_id': customer.id}
            
            # Find the most recent active subscription, or the most recent one if none are active
            active_subscription = None
            most_recent_subscription = subscriptions.data[0]  # Most recent subscription
            
            for sub in subscriptions.data:
                if sub.status == 'active':
                    active_subscription = sub
                    break
            
            # Use active subscription if found, otherwise use most recent
            subscription = active_subscription or most_recent_subscription
            logger.info(f"Using subscription: {subscription.id} with status: {subscription.status}")
            
            # Use dictionary-style access since the JSON shows the structure is there
            try:
                # Convert subscription to dict if needed to access items
                subscription_dict = dict(subscription) if hasattr(subscription, '__iter__') else subscription
                
                if 'items' not in subscription_dict or not subscription_dict['items']['data']:
                    logger.warning(f"Subscription {subscription.id} has no items in dict format")
                    return {'status': subscription.status, 'customer_id': customer.id}
                
                # Get the first subscription item
                subscription_item_dict = subscription_dict['items']['data'][0]
                logger.info(f"Got subscription item from dict: {subscription_item_dict['id']}")
                
                # Extract price and product info from dict
                price_dict = subscription_item_dict['price']
                product_id = price_dict['product']
                
                logger.info(f"Subscription item - Price ID: {price_dict['id']}, Product ID: {product_id}")
                
            except Exception as dict_error:
                logger.error(f"Error accessing subscription via dict: {str(dict_error)}")
                # Fallback: try to use subscription item list API call
                try:
                    subscription_items = stripe.SubscriptionItem.list(
                        subscription=subscription.id,
                        api_key=self.stripe_api_key
                    )
                    if not subscription_items.data:
                        return {'status': subscription.status, 'customer_id': customer.id}
                    subscription_item = subscription_items.data[0]
                    price_dict = {'id': subscription_item.price.id, 'product': subscription_item.price.product}
                    product_id = subscription_item.price.product
                except Exception as fallback_error:
                    logger.error(f"Fallback failed: {str(fallback_error)}")
                    return {'status': subscription.status, 'customer_id': customer.id}
            
            # Retrieve the product details separately
            product_name = f"Product {product_id}"  # Default fallback
            try:
                product_obj = stripe.Product.retrieve(product_id, api_key=self.stripe_api_key)
                product_name = product_obj.name
            except Exception as product_error:
                logger.error(f"Error fetching product details for {product_id}: {str(product_error)}")
                product_name = f"Product {product_id}"
            
            # Build plan information
            plan_info = {
                'product_id': product_id,
                'product_name': product_name,
                'price_id': price_dict.get('id'),
                'amount': price_dict.get('unit_amount', 0),
                'currency': price_dict.get('currency', 'usd'),
                'interval': price_dict.get('recurring', {}).get('interval', 'one_time') if price_dict.get('recurring') else 'one_time',
                'nickname': price_dict.get('nickname')
            }
            
            return {
                'status': subscription.status,
                'subscription_id': subscription.id,
                'current_period_end': getattr(subscription, 'current_period_end', None),
                'current_period_start': getattr(subscription, 'current_period_start', None),
                'customer_id': customer.id,
                'plan_info': plan_info
            }

        except stripe.error.RateLimitError as e:
            # Too many requests
            logger.error(f"Rate limit error getting subscription status for {customer_email}: {str(e)}")
            return None
        except stripe.error.InvalidRequestError as e:
            # Invalid parameters
            logger.error(f"Invalid request getting subscription status for {customer_email}: {str(e)}")
            return None
        except stripe.error.AuthenticationError as e:
            # Authentication failed
            logger.error(f"Authentication error getting subscription status for {customer_email}: {str(e)}")
            return None
        except stripe.error.APIConnectionError as e:
            # Network communication failed
            logger.error(f"Network error getting subscription status for {customer_email}: {str(e)}")
            return None
        except stripe.error.StripeError as e:
            # Generic Stripe error
            logger.error(f"Stripe error getting subscription status for {customer_email}: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error getting subscription status for {customer_email}: {str(e)}")
            return None
    
    def create_billing_portal_session(self, customer_id: str) -> Optional[str]:
        """Create a billing portal session for customer to manage subscription"""
        try:
            create_args = {
                'customer': customer_id,
                'return_url': self.frontend_url,
            }
            # If a specific configuration is provided, pass it to avoid relying on a default
            if self.billing_portal_configuration_id:
                create_args['configuration'] = self.billing_portal_configuration_id

            create_args['api_key'] = self.stripe_api_key

            session = stripe.billing_portal.Session.create(**create_args)
            return session.url
        except stripe.error.RateLimitError as e:
            # Too many requests
            logger.error(f"Rate limit error creating billing portal session: {str(e)}")
            return None
        except stripe.error.InvalidRequestError as e:
            # Invalid parameters
            logger.error(f"Invalid request creating billing portal session: {str(e)}")
            # Provide actionable guidance when no configuration is set in test mode
            if 'No configuration provided' in str(e):
                logger.warning(
                    "Stripe billing portal requires a default configuration in test mode or a specific\n"
                    "configuration ID. Either: (1) set a default at https://dashboard.stripe.com/test/settings/billing/portal\n"
                    "or (2) set STRIPE_BILLING_PORTAL_CONFIGURATION_ID and restart the server."
                )
            return None
        except stripe.error.AuthenticationError as e:
            # Authentication failed
            logger.error(f"Authentication error creating billing portal session: {str(e)}")
            return None
        except stripe.error.APIConnectionError as e:
            # Network communication failed
            logger.error(f"Network error creating billing portal session: {str(e)}")
            return None
        except stripe.error.StripeError as e:
            # Generic Stripe error
            logger.error(f"Stripe error creating billing portal session: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error creating billing portal session: {str(e)}")
            return None
    
    def get_subscription_plans(self) -> Dict[str, Any]:
        """Get available subscription plans from Stripe"""
        # Product name to add custom features to
        CUSTOM_FEATURES_PRODUCT_NAME = "Pro"
        
        # Custom features for the test product
        CUSTOM_FEATURES = [
            "Unlimited AI-powered code generation",
            "Advanced repository analysis with semantic search", 
            "Real-time collaborative development environment",
            "Priority support with dedicated developer assistance",
            "Enterprise-grade security and compliance features"
        ]
        plans_db = SubscriptionPlanDB()

        try:
            cached_plans = plans_db.get_recent_plans()
            if cached_plans:
                return {
                    'plans': cached_plans,
                    'total_count': len(cached_plans)
                }

            # Get all products and their prices from Stripe
            products = stripe.Product.list(active=True, limit=100, api_key=self.stripe_api_key)

            plans = []

            for product in products.data:

                # Get prices for this product
                prices = stripe.Price.list(
                    product=product.id,
                    active=True,
                    limit=100,
                    api_key=self.stripe_api_key
                )
                for price in prices.data:
                    # Get base features from Stripe metadata
                    base_features = product.metadata.get('features', '').split(',') if product.metadata.get('features') else []
                    
                    # Add custom features if this is the test product
                    if product.name == CUSTOM_FEATURES_PRODUCT_NAME:
                        features = CUSTOM_FEATURES
                    else:
                        features = base_features
                    
                    plan_data = {
                        'product_id': product.id,
                        'product_name': product.name,
                        'product_description': product.description or '',
                        'price_id': price.id,
                        'price_nickname': price.nickname,
                        'amount': price.unit_amount,
                        'currency': price.currency,
                        'interval': price.recurring.interval if price.recurring else 'one_time',
                        'interval_count': price.recurring.interval_count if price.recurring else 1,
                        'type': 'subscription' if price.recurring else 'one_time',
                        'features': features
                    }
                    
                    plans.append(plan_data)
            
            plans_db.upsert_plans(plans)
            plans_db.purge_stale_plans()
            
            return {
                'plans': plans,
                'total_count': len(plans)
            }

        except stripe.error.RateLimitError as e:
            # Too many requests
            logger.error(f"Rate limit error fetching subscription plans: {str(e)}")
            return {'plans': [], 'error': 'Too many requests. Please try again in a moment.'}
        except stripe.error.InvalidRequestError as e:
            # Invalid parameters
            logger.error(f"Invalid request fetching subscription plans: {str(e)}")
            return {'plans': [], 'error': 'Invalid request. Please contact support.'}
        except stripe.error.AuthenticationError as e:
            # Authentication failed
            logger.error(f"Authentication error fetching subscription plans: {str(e)}")
            return {'plans': [], 'error': 'Payment system configuration error. Please contact support.'}
        except stripe.error.APIConnectionError as e:
            # Network communication failed
            logger.error(f"Network error fetching subscription plans: {str(e)}")
            return {'plans': [], 'error': 'Network error. Please try again.'}
        except stripe.error.StripeError as e:
            # Generic Stripe error
            logger.error(f"Stripe error fetching subscription plans: {str(e)}")
            return {'plans': [], 'error': 'Unable to fetch subscription plans'}
        except Exception as e:
            logger.error(f"Unexpected error fetching subscription plans: {str(e)}")
            return {'plans': [], 'error': 'Service temporarily unavailable'}

# Create a singleton instance (lazy initialization)
_stripe_client = None

def get_stripe_client():
    global _stripe_client
    if _stripe_client is None:
        _stripe_client = StripeClient()
    return _stripe_client

# For backward compatibility
stripe_client = get_stripe_client 
