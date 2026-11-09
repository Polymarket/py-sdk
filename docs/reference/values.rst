Types and Values
################

Environment
-----------

.. autoclass:: polymarket.Environment
   :members:
   :undoc-members:

EvmAddress
----------

.. py:data:: polymarket.EvmAddress
   :type: str

   A checks-only type marker for an EVM address string.

PRODUCTION
----------

.. py:data:: polymarket.PRODUCTION
   :type: Environment

   The production Polymarket environment.

to_combo_condition_id
---------------------

.. autofunction:: polymarket.to_combo_condition_id

Version
-------

.. py:data:: polymarket.__version__
   :type: str

   The installed SDK version.

Directional identifiers
------------------------

.. autofunction:: polymarket.decode_position_id

.. autofunction:: polymarket.derive_directional_bucket_positions

.. autofunction:: polymarket.derive_directional_threshold_positions
