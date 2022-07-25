import os
import time
import stripe

PLATFORM1_SECRET_KEY = os.getenv('PLATFORM1_SECRET_KEY')
PLATFORM2_SECRET_KEY = os.getenv('PLATFORM2_SECRET_KEY')

stripe.api_key = PLATFORM1_SECRET_KEY

# NOTE: Populate these account IDs with your test account IDs
PLATFORM1_ACCOUNT_ID = 'acct_1LPQErIUWRzULeRH'
PLATFORM2_ACCOUNT_ID = 'acct_1LPSFgLHpZuxSd6f'

TEST_ROUTING_NUMBER_US = '110000000'
TEST_ACCOUNT_NUMBER_US = '000123456789'

TEST_ROUTING_NUMBER_AU = '110000'
TEST_ACCOUNT_NUMBER_AU = '000123456'

def swap_platform1_context():
  stripe.api_key = PLATFORM1_SECRET_KEY

def swap_platform2_context():
  stripe.api_key= PLATFORM2_SECRET_KEY

def create_connect_account(email, country='US'):
  if country == 'AU':
    return __create_connect_account_au(email)

  return __create_connect_account_us(email)

# Helper function to create a Custom Stripe Connect Account with treasury capabilities
# that is fully validated with the exception of having an external account
def __create_connect_account_us(email):
  return stripe.Account.create(
    type='custom',
    country='US',
    email=email,
    capabilities={
      'card_payments': {'requested': True},
      'transfers': {'requested': True},
    },
    business_profile={
      'name': 'My Biz',
      'mcc': '5734',
      'url': 'https://mybiz.com',
      'product_description': 'Test test test',
    },
    business_type='individual',
    default_currency='usd',
    external_account={
      'object': 'bank_account',
      'country': 'US',
      'currency': 'usd',
      'account_number': TEST_ACCOUNT_NUMBER_US,
      'routing_number': TEST_ROUTING_NUMBER_US,
    },
    individual={
      'address': {
        'city': 'Raleigh',
        'country': 'US',
        'line1': '500 Glenwood Ave',
        'postal_code': '27603',
        'state': 'NC',
      },
      'email': 'connect.one@example.com',
      'first_name': 'Connect',
      'last_name': 'One',
      'dob': {
        'day': 1,
        'month': 1,
        'year': 1990,
      },
      'id_number': '123456789',
      'phone': '0000000000',
      'verification': {
        'document': {
          'front': 'file_identity_document_success',
        },
      },
    },
    tos_acceptance={
      'date': int(time.time()),
      'ip': '123.123.123.123',
    },
    stripe_account=PLATFORM2_ACCOUNT_ID
  )

# Helper function to create a Custom Stripe Connect Account with treasury capabilities
# that is fully validated with the exception of having an external account
def __create_connect_account_au(email):
  return stripe.Account.create(
    type='custom',
    country='AU',
    email=email,
    capabilities={
      'card_payments': {'requested': True},
      'transfers': {'requested': True},
    },
    business_profile={
      'name': 'My Biz',
      'mcc': '5734',
      'url': 'https://mybiz.com',
      'product_description': 'Test test test',
    },
    business_type='individual',
    default_currency='aud',
    external_account={
      'object': 'bank_account',
      'country': 'AU',
      'currency': 'aud',
      'account_number': TEST_ACCOUNT_NUMBER_AU,
      'routing_number': TEST_ROUTING_NUMBER_AU,
    },
    individual={
      'address': {
        'city': 'Melbourne',
        'country': 'AU',
        'line1': '180 St Kilda Rd',
        'postal_code': '3006',
        'state': 'Victoria',
      },
      'email': 'connect.one@example.com',
      'first_name': 'Connect',
      'last_name': 'One',
      'dob': {
        'day': 1,
        'month': 1,
        'year': 1990,
      },
      'id_number': '123456789',
      'phone': '0000000000',
      'verification': {
        'document': {
          'front': 'file_identity_document_success',
        },
      },
    },
    tos_acceptance={
      'date': int(time.time()),
      'ip': '123.123.123.123',
    },
    stripe_account=PLATFORM2_ACCOUNT_ID
  )

def wait_for_fa_to_init(account, financial_account):
  max_wait = 120
  counter = 0

  print('[+] Waiting for FA to get the necessary features enabled...')
  while 'inbound_transfers.ach' not in financial_account.active_features and counter < max_wait:
    time.sleep(1)
    financial_account = stripe.treasury.FinancialAccount.retrieve(
      financial_account.id,
      stripe_account=account.id
    )

    counter += 1

  return counter < max_wait

def get_customer_payment_methods(customer):
  payment_method_cards = stripe.Customer.list_payment_methods(
    customer.id,
    type='card'
  )
  payment_method_bank_accounts = stripe.Customer.list_payment_methods(
    customer.id,
    type='us_bank_account',
  )

  return payment_method_cards.data + payment_method_bank_accounts.data 

# NOTE: Going into this function, the API key being used is PLATFORM1_SECRET_KEY
def test_share_payment_methods(customer):
  #########################################################################
  # Get the payment methods on this Customer object
  #   Types can be src, card, ba, or pm
  #########################################################################

  # NOTE: The list_payment_methods function lists both card_XXX/ba_XXX and pm_XXX types
  #cards = stripe.Customer.list_sources(
  #  customer.id,
  #  object='card'
  #)
  #bank_accounts = stripe.Customer.list_sources(
  #  customer.id,
  #  object='bank_account'
  #)

  # NOTE: Doesn't seem to be possible to retrieve a Source type of ach_credit_transfer
  # so we'll pass that in manually (assuming the source ID is saved to a database)
  pm_list = get_customer_payment_methods(customer)
  print('[+] Found {} total payment methods attached to customer {}'.format(len(pm_list), customer.id))
  for pm in pm_list:
    print(pm.id)

  #########################################################################
  # Creating an AU-based Connect Account on the AU platform
  #########################################################################
  print('[+] Creating an AU-based Connect Account to charge...')

  # NOTE Need to run this API call as the child platform in order for it to work
  swap_platform2_context()
  account = create_connect_account(customer.email, country='AU')
  swap_platform1_context()

  print('[+] Done! Attempting to JIT clone and charge payment methods...')
  time.sleep(5)

  pm_list = get_customer_payment_methods(customer)
  for pm in pm_list:
    _pm = stripe.PaymentMethod.create(
      customer=customer.id,
      payment_method=pm.id,
      stripe_account=PLATFORM2_ACCOUNT_ID
    )

    # NOTE: Need to swap over to the child platform's API keys to create a destination charge on the child's Connect Account
    swap_platform2_context()
    _pi = stripe.PaymentIntent.create(
      amount=1000,
      currency='aud',
      payment_method_types=['card'],
      payment_method=_pm.id,
      confirm=True,
      on_behalf_of=account.id,
      transfer_data={
        'destination': account.id,
      },
      application_fee_amount=500,
      stripe_account=PLATFORM2_ACCOUNT_ID
    )
    swap_platform1_context()

  print('[+] Done!')



def create_customer(name, email):
  return stripe.Customer.create(
    email=email,
    name=name,
  )

def create_card_card(customer):
  tok = stripe.Token.create(
    card={
      'object': 'card',
      # NOTE: MUST be a debit card!
      'number': '4000056655665556',
      'exp_month': 1,
      'exp_year': 23,
      'cvc': 123,
      # NOTE: currency MUST be set in order to attach this to a Connect Account
      # as an external debit card later!
      'currency': 'usd',
      'name': 'Jenny Rosen',
      'address_zip': '12345',
    },
  )

  return stripe.Customer.create_source(
    customer.id,
    source=tok
  )

def create_card_card(customer):
  tok = stripe.Token.create(
    card={
      'object': 'card',
      # NOTE: MUST be a debit card!
      'number': '4000056655665556',
      'exp_month': 1,
      'exp_year': 23,
      'cvc': 123,
      # NOTE: currency MUST be set in order to attach this to a Connect Account
      # as an external debit card later!
      'currency': 'usd',
      'name': 'Jenny Rosen',
      'address_zip': '12345',
    },
  )

  return stripe.Customer.create_source(
    customer.id,
    source=tok
  )

def create_card_pm(customer):
  pm = stripe.PaymentMethod.create(
    type='card',
    card={
      # NOTE: MUST be a debit card!
      'number': '4000056655665556',
      'exp_month': 1,
      'exp_year': 23,
      'cvc': 123,
    },
  )

  seti = stripe.SetupIntent.create(
    payment_method=pm.id,
    confirm=True,
    customer=customer.id,
    payment_method_types=['card'],
  )

  return stripe.PaymentMethod.retrieve(seti.payment_method)


# Create a Customer with every type of payment method
# Show all the ways in which these payment methods can be re-used on another platform
# (Attach to Customers for pay-ins, attach to Connect Accounts for payouts,
# Attach to Connect Accounts for Treasury money movement)
def customer_clone_test():
  name = 'Customer Test-Full-Clone'
  email = 'customer.test.full.clone+{}@example.com'

  print('[+] Creating a test customer for this test with several payment methods...')
  customer = create_customer(name, email)

  # Attach 2 payment methods (bank account should be default)
  card1 = create_card_card(customer)
  print('[+] Attached a debit card as a card_XXX object')
  card2 = create_card_pm(customer)
  print('[+] Attached a debit card as a pm_XXX object')

  print('[+] Attempting to fully clone this customer over to another platform')
  test_share_payment_methods(customer)


customer_clone_test()
