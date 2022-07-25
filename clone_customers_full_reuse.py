import os
import time
import stripe

PLATFORM1_SECRET_KEY = os.getenv('PLATFORM1_SECRET_KEY')
PLATFORM2_SECRET_KEY = os.getenv('PLATFORM2_SECRET_KEY')

stripe.api_key = PLATFORM2_SECRET_KEY

# NOTE: Populate these account IDs with your test account IDs
PLATFORM1_ACCOUNT_ID = 'acct_1KqSGtCXnmk0hO7C'
PLATFORM2_ACCOUNT_ID = 'acct_1LLob0Lv0bUBVQly'

TEST_ROUTING_NUMBER = '110000000'
TEST_ACCOUNT_NUMBER = '000123456789'

def swap_platform1_context():
  stripe.api_key = PLATFORM1_SECRET_KEY

def swap_platform2_context():
  stripe.api_key= PLATFORM2_SECRET_KEY

# Helper function to create a Custom Stripe Connect Account with treasury capabilities
# that is fully validated with the exception of having an external account
def create_connect_account(email):
  return stripe.Account.create(
    type='custom',
    country='US',
    email=email,
    capabilities={
      'card_payments': {'requested': True},
      'transfers': {'requested': True},
      'treasury': {'requested': True},
      'us_bank_account_ach_payments': {'requested': True},
    },
    business_profile={
      'name': 'My Biz',
      'mcc': '5734',
      'url': 'https://mybiz.com',
      'product_description': 'Test test test',
    },
    business_type='individual',
    default_currency='usd',
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
    settings={
      'treasury': {
        'tos_acceptance': {
          'date': int(time.time()),
          'ip': '123.123.123.123',
        },
      },
    },
    tos_acceptance={
      'date': int(time.time()),
      'ip': '123.123.123.123',
    },
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

# NOTE: Going into this function, the API key being used is for the Fleet platform account
def customer_full_clone(customer, ach_credit_source_id):
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
  # Create the Customer on the wallet/Treasury platform
  #########################################################################
  print('[+] Creating a copy of this Customer on the other platform account...')

  new_customer = stripe.Customer.create(
    name=customer.name,
    email=customer.email,
    # Any other params to copy over...
    stripe_account=PLATFORM2_ACCOUNT_ID
  )

  #########################################################################
  # Move the payment methods over to the new Customer
  #   This will depend on the payment method type
  #########################################################################
  for pm in pm_list:
    if pm.id.startswith('card_'):
      # Copy it over using the Tokens API and attach it the Customer

      # For payment methods that start with card_XXX, these can be re-used as external accounts for a Connect Account (if it's a debit card)

      # If you use the PaymentMethod API to copy this over, it will convert from a card_XXX to a pm_XXX and lose that
      # ability. That's why in this case I explicitly call the Tokens API

      print('[+] Moving payment method {} over to the new platform...'.format(pm.id))

      # Reference: https://stripe.com/docs/api/tokens/create_card
      tok = stripe.Token.create(
        card=pm.id,
        customer=customer.id,
        stripe_account=PLATFORM2_ACCOUNT_ID
      )

      # Reference: https://stripe.com/docs/api/cards/create
      stripe.Customer.create_source(
        new_customer.id,
        source=tok,
        stripe_account=PLATFORM2_ACCOUNT_ID
      )

      continue

    elif pm.id.startswith('ba_'):
      # Copy it over using the Tokens API and attach it the Customer

      # For payment methods that start with ba_XXX, these can be re-used as external accounts for a Connect Account

      # If you use the PaymentMethod API to copy this over, it will convert from a ba_XXX to a pm_XXX and lose that
      # ability. That's why in this case I explicitly call the Tokens API

      print('[+] Moving payment method {} over to the new platform...'.format(pm.id))

      # Reference: https://stripe.com/docs/api/tokens/create_bank_account
      btok = stripe.Token.create(
        bank_account=pm.id,
        customer=customer.id,
        stripe_account=PLATFORM2_ACCOUNT_ID
      )

      # Reference: https://stripe.com/docs/api/customer_bank_accounts/create
      new_src = stripe.Customer.create_source(
        new_customer.id,
        source=btok,
        stripe_account=PLATFORM2_ACCOUNT_ID
      )

      # NOTE: The ID for new_src doesn't change after going through this SetupIntent
      # But this SetupIntent is necessary to attach the mandate data to it so it can be charged
      seti = stripe.SetupIntent.create(
        customer=new_customer.id,
        confirm=True,
        mandate_data={
          'customer_acceptance': {
            'type': 'offline',
          },
        },
        payment_method=new_src.id,
        payment_method_types=['us_bank_account'],
        stripe_account=PLATFORM2_ACCOUNT_ID
      )

      continue

    elif pm.id.startswith('pm_'):
      # Copy it over using the PaymentMethods API and attach it the Customer

      print('[+] Moving payment method {} over to the new platform...'.format(pm.id))

      # Reference: https://stripe.com/docs/payments/payment-methods/connect#cloning-payment-methods
      _pm = stripe.PaymentMethod.create(
        customer=customer.id,
        payment_method=pm.id,
        stripe_account=PLATFORM2_ACCOUNT_ID
      )

      # Reference: https://stripe.com/docs/api/payment_methods/attach
      stripe.PaymentMethod.attach(
        _pm.id,
        customer=new_customer.id,
        stripe_account=PLATFORM2_ACCOUNT_ID
      )

      continue

    elif pm.id.startswith('src_'):
      print('[-] This type of payment method object ({}) can\'t be shared across platforms...'.format(pm.id))

      # Can't be copied over using Stripe's API; try to get the bank account details
      # from Plaid to re-create the Payment Method on the wallet/Treasury platform
      pass

  #########################################################################
  # Change over into the wallet context
  #########################################################################
  swap_platform2_context()

  #########################################################################
  # Create charges with each of these payment methods to show that they work to collect funds
  #########################################################################
  print('[+] Attempting to charge all copied payment methods to verify ability for pay-ins...')

  pm_list = get_customer_payment_methods(new_customer)
  for pm in pm_list:
    payment_method_types = []

    if pm.id.startswith('ba_') or (pm.id.startswith('pm_') and pm.type == 'us_bank_account'):
      payment_method_types.append('us_bank_account')

    elif pm.id.startswith('card_') or (pm.id.startswith('pm_') and pm.type == 'card'):
      payment_method_types.append('card')

    _pi = stripe.PaymentIntent.create(
      amount=1000,
      currency='usd',
      customer=new_customer.id,
      payment_method_types=payment_method_types,
      payment_method=pm.id,
      confirm=True
    )

  #########################################################################
  # Create a Connect Account for the Customer and reuse as much info as possible
  #########################################################################
  print('[+] Creating a Custom Connect Account...')
  account = create_connect_account(new_customer.email)
  print('[+] Account created!')

  #########################################################################
  # Create a Financial Account
  #########################################################################
  print('[+] Creating a FinancialAccount (FA) for the Connect Account...')
  fa = stripe.treasury.FinancialAccount.create(
    supported_currencies=['usd'],
    features={
      #'card_issuing': {'requested': True},
      'deposit_insurance': {'requested': True},
      'financial_addresses': {
        'aba': {'requested': True},
      },
      'inbound_transfers': {
        'ach': {'requested': True},
      },
      'intra_stripe_flows': {'requested': True},
      'outbound_payments': {
        'ach': {'requested': True},
        'us_domestic_wire': {'requested': True},
      },
      'outbound_transfers': {
        'ach': {'requested': True},
        'us_domestic_wire': {'requested': True},
      },
    },
    stripe_account=account.id
  )
  print('[+] FA created successfully!')

  #########################################################################
  # Attach any viable payment methods to this account as an external account
  # (NOTE: The only ones we can attach are the card_XXX object (if it's a debit card) and ba_XXX object)
  #########################################################################

  external_account_card = None
  external_account_bank = None

  print('[+] Attaching any card_XXX or ba_XXX payment methods as an external account for the Connect Account...')

  # Attach a card_XXX object as an external account
  cards = stripe.Customer.list_payment_methods(
    new_customer.id,
    type='card'
  )

  # Iterate over card type payment methods
  for card in cards.data:
    # Search for the payment method with an ID that starts with card_ and is a debit card
    if card.id.startswith('card_') and card.card.funding == 'debit':
      # Create a Token for the debit card
      tok = stripe.Token.create(
        customer=new_customer.id,
        card=card.id,
        stripe_account=account.id
      )

      _account = stripe.Account.retrieve(account.id)
      if len(_account.external_accounts.data) > 0:
        # If there's already an external account attached to this Connect Account, we need
        # to use this API call to add a new external account (instead of replacing)
        # Reference: https://stripe.com/docs/connect/payouts-bank-accounts#multiple-accounts

        # Attach the debit card as an external account for payouts
        external_account_card = stripe.Account.create_external_account(
          account.id,
          external_account=tok.id
        )
        print('[+] Added payment method {} as an external account'.format(bank_account.id))
      else:
        # There is no external account for this Connect Account yet so just add it as normal
        # Reference: https://stripe.com/docs/api/accounts/update
        external_account_card = stripe.Account.modify(
          account.id,
          external_account=tok.id,
        )
        print('[+] Updated the external account to payment method with ID {}'.format(card.id))

  # Attach a ba_XXX object as an external account
  bank_accounts = stripe.Customer.list_payment_methods(
    new_customer.id,
    type='us_bank_account'
  )

  # Iterate over bank account type payment methods
  for bank_account in bank_accounts.data:
    # Search for the payment method with an ID that starts with ba_
    if bank_account.id.startswith('ba_'):
      # Create a Token for the bank account
      btok = stripe.Token.create(
        customer=new_customer.id,
        bank_account=bank_account.id,
        stripe_account=account.id
      )

      _account = stripe.Account.retrieve(account.id)
      if len(_account.external_accounts.data) > 0:
        # If there's already an external account attached to this Connect Account, we need
        # to use this API call to add a new external account (instead of replacing)
        # Reference: https://stripe.com/docs/connect/payouts-bank-accounts#multiple-accounts

        # Attach the bank account as an external account for payouts
        external_account_bank = stripe.Account.create_external_account(
          account.id,
          external_account=btok.id
        )
        print('[+] Added payment method {} as an external account'.format(bank_account.id))
      else:
        # There is no external account for this Connect Account yet so just add it as normal
        # Reference: https://stripe.com/docs/api/accounts/update
        external_account_bank = stripe.Account.modify(
          account.id,
          external_account=btok.id,
        )
        print('[+] Updated the external account to payment method with ID {}'.format(bank_account.id))

  #########################################################################
  # Attach any viable payment methods as Treasury money movement accounts
  # NOTE: Only bank accounts (for ACH debit) can be used for Treasury money movement
  #########################################################################
  print('[+] Updating payment methods to be used by the Connect Account for Treasury money movement...')

  bank_account_pms_treasury = []

  for bank_account in bank_accounts:
    _pm = stripe.PaymentMethod.create(
      customer=new_customer.id,
      payment_method=bank_account.id,
      stripe_account=account.id
    )

    seti = stripe.SetupIntent.create(
      attach_to_self=True,
      payment_method=_pm.id,
      flow_directions=['inbound', 'outbound',],
      payment_method_types=['us_bank_account'],
      confirm=True,
      mandate_data={
        'customer_acceptance': {
          'type': 'offline',
        },
      },
      stripe_account=account.id,
    )

    bank_account_pms_treasury.append(seti.payment_method)

    print('[+] Successfully setup payment method {} for Treasury flows'.format(bank_account.id))

  #########################################################################
  # Create InboundTransfers using these new payment methods to make sure they work
  #########################################################################
  print('[+] Creating InboundTransfers to test payment methods for Treasury money movement...')

  # Wait for the FinancialAccount to fully init and get the capabilities it needs
  result = wait_for_fa_to_init(account, fa)
  if not result:
    print('[!] FinancialAccount never fully initialized :(')
    return

  for pm in bank_account_pms_treasury:
    it = stripe.treasury.InboundTransfer.create(
      amount=12300,
      currency='usd',
      origin_payment_method=pm,
      financial_account=fa.id,
      stripe_account=account.id
    )

  print('[+] Done!')
  
  

def create_customer(name, email):
  return stripe.Customer.create(
    email=email,
    name=name,
  )

def create_bank_account_ba(customer):
  return stripe.Customer.create_source(
    customer.id,
    source={
      'object': 'bank_account',
      'country': 'US',
      'currency': 'usd',
      'account_holder_name': 'Jenny Rosen',
      'account_holder_type': 'individual',
      'routing_number': TEST_ROUTING_NUMBER,
      'account_number': TEST_ACCOUNT_NUMBER,
    },
  )

def create_bank_account_src(customer):
  bank_account = create_bank_account_ba(customer)

  source = stripe.Source.create(
    type='ach_credit_transfer',
    currency='usd',
    owner={
      'email': customer.email,
      'name': customer.name,
    },
    token=bank_account.id,
  )

  # Attach the source to the Customer
  source = stripe.Customer.create_source(
    customer.id,
    source=source.id
  )

  bank_accounts = stripe.Customer.list_sources(
    customer.id,
    object='bank_account'
  )

  # For some reason, a ba_XXX object is also being created
  stripe.Customer.delete_source(
    customer.id,
    bank_accounts.data[0].id,
  )

  return source

def create_bank_account_pm_connections(customer):
  session = stripe.checkout.Session.create(
    success_url='https://example.com/success',
    cancel_url='https://example.com/cancel',
    mode='setup',
    customer=customer.id,
    payment_method_types=['us_bank_account']
  )

  print('[+] Visit this URL to setup your bank account. After two minutes of inactivity, this script will exit:')
  print(session.url)

  max_wait = 120
  counter = 0

  while not session.status == 'complete' and counter < max_wait:
    time.sleep(1)
    session = stripe.checkout.Session.retrieve(session.id)

  if counter >= max_wait:
    print('[!] Bank account setup never completed. Exiting')
    exit(0)

  seti = stripe.SetupIntent.retrieve(session.setup_intent)

  return seti

def create_bank_account_pm(customer):
  return stripe.SetupIntent.create(
    customer=customer.id,
    confirm=True,
    mandate_data={
      'customer_acceptance': {
        'type': 'offline',
      },
    },
    payment_method_types=['us_bank_account'],
    payment_method_data={
      'type': 'us_bank_account',
      'billing_details': {
        'name': 'Jenny Rosen',
      },
      'us_bank_account': {
        'account_holder_type': 'individual',
        'account_number': TEST_ACCOUNT_NUMBER,
        'routing_number': TEST_ROUTING_NUMBER,
      },
    },
    payment_method_options={
      'us_bank_account': {
        'verification_method': 'microdeposits',
      },
    },
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

def create_card_src(customer):
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

  source = stripe.Source.create(
    type='card',
    currency='usd',
    owner={
      'email': customer.email,
      'name': customer.name,
    },
    token=tok.id,
  )

  # Attach the source to the Customer
  return stripe.Customer.create_source(
    customer.id,
    source=source.id
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

def verify_bank_account_ba(customer, bank_account):
  bank_account = stripe.Customer.retrieve_source(
    customer.id,
    bank_account.id,
  )

  bank_account.verify(amounts=[32, 45])

def verify_bank_account_pm(customer, seti):
  stripe.stripe_object.StripeObject().request('post', '/v1/setup_intents/{}/verify_microdeposits'.format(seti.id), {
    "amounts": [
      32,
      45
    ]
  })


# Create a Customer with every type of payment method
# Show all the ways in which these payment methods can be re-used on another platform
# (Attach to Customers for pay-ins, attach to Connect Accounts for payouts,
# Attach to Connect Accounts for Treasury money movement)
def customer_clone_test():
  swap_platform1_context()

  name = 'Customer Test-Full-Clone'
  email = 'customer.test.full.clone+{}@example.com'

  print('[+] Creating a test customer for this test with several payment methods...')
  customer = create_customer(name, email)

  # Attach 2 payment methods (bank account should be default)
  card1 = create_card_card(customer)
  print('[+] Attached a debit card as a card_XXX object')
  card2 = create_card_pm(customer)
  print('[+] Attached a debit card as a pm_XXX object')

  bank_account1 = create_bank_account_src(customer)
  print('[+] Attached a bank account (ACH credit) as a src_XXX object')
  bank_account2 = create_bank_account_ba(customer)
  print('[+] Attached a bank account (ACH debit) as a ba_XXX object')
  verify_bank_account_ba(customer, bank_account2)
  print('... and verified that bank account using microdeposits')

  USE_FINANCIAL_CONNECTIONS = True
  if USE_FINANCIAL_CONNECTIONS:
    print('[+] Attempting to create a bank account (ACH debit) as a pm_XXX object using Financial Connections...')
    bank_account3 = create_bank_account_pm_connections(customer)
    print('[+] Bank account created! No verification required.')
  else:
    bank_account3 = create_bank_account_pm(customer)
    print('[+] Attached a bank account (ACH debit) as a pm_XXX object')
    verify_bank_account_pm(customer, bank_account3)
    print('... and verified that bank account using microdeposits')

  print('[+] Attempting to fully clone this customer over to another platform')
  customer_full_clone(customer, bank_account1.id)


customer_clone_test()
