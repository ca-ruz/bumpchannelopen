#!/usr/bin/env python3
from pyln.client import Plugin, RpcError
import json
from bitcointx.core.psbt import PartiallySignedTransaction
from bitcoinrpc.authproxy import AuthServiceProxy, JSONRPCException
import os

plugin = Plugin()

class CPFPError(Exception):
    pass

plugin.add_option('bump_brpc_user', None, 'bitcoin rpc user')
plugin.add_option('bump_brpc_pass', None, 'bitcoin rpc password')
plugin.add_option('bump_brpc_port', 18443, 'bitcoin rpc port')


def connect_bitcoincli(rpc_user="__cookie__", rpc_password=None, host="127.0.0.1", port=18443):
    """
    Connects to a Bitcoin Core RPC server.

    Args:
        rpc_user (str): The RPC username, default is '__cookie__' for cookie authentication.
        rpc_password (str): The RPC password or cookie value (default: None).
        host (str): The RPC host, default is '127.0.0.1'.
        port (int): The RPC port, default is 18443.

    Returns:
        AuthServiceProxy: The RPC connection object.
    """
    # try:
    #     rpc_connection_test = rpc_connection.getblockchaininfo()

    # Use the specified cookie file path for regtest

    if rpc_password is None:
        # Attempt to retrieve the cookie value from the regtest .cookie file
        try:
            cookie_path = os.path.expanduser("~/.bitcoin/regtest/.cookie")
            with open(cookie_path, "r") as cookie_file:
                rpc_user, rpc_password = cookie_file.read().strip().split(":")
        except FileNotFoundError:
            raise FileNotFoundError("Could not find the .cookie file. Ensure Bitcoin Core is running with cookie-based auth enabled.")
    
    rpc_url = f"http://{rpc_user}:{rpc_password}@{host}:{port}"

    plugin.log("rpc_url: %s" % rpc_url)
    
    try:
        rpc_connection = AuthServiceProxy(rpc_url)
        return rpc_connection
    except Exception as e:
        raise ConnectionError(f"Error connecting to Bitcoin Core: {e}")
    

def calculate_confirmed_unreserved_amount(json_data):
    """
    Calculates the total amount in satoshis for outputs that are confirmed and not reserved.

    :param json_data: A dictionary parsed from the JSON structure
    :return: Total amount in satoshis
    """
    total_amount_sats = 0

    # Ensure the "outputs" field exists in the JSON data
    if "outputs" in json_data:
        for output in json_data["outputs"]:
            if (
                output.get("status") == "confirmed" and  # Check for confirmed status
                not output.get("reserved", False)        # Check if not reserved
            ):
                # Convert amount_msat (millisatoshis) to satoshis and add to total
                total_amount_sats += output.get("amount_msat", 0) // 1000

    return total_amount_sats


# def estimate_tx_size(num_inputs, num_outputs, input_type="P2WPKH", output_type="P2WPKH"):
#     """
#     Estimate the size of the transaction based on input and output types.

#     :param num_inputs: Number of inputs.
#     :param num_outputs: Number of outputs.
#     :param input_type: Type of input (e.g., "P2PKH", "P2WPKH", "P2SH-P2WPKH").
#     :param output_type: Type of output (e.g., "P2PKH", "P2WPKH").
#     :return: Estimated transaction size in bytes.
#     """
#     input_sizes = {"P2PKH": 148, "P2WPKH": 68, "P2SH-P2WPKH": 91}
#     output_sizes = {"P2PKH": 34, "P2WPKH": 31}

#     input_size = input_sizes.get(input_type, 148)  # Default to P2PKH
#     output_size = output_sizes.get(output_type, 34)  # Default to P2PKH

#     base_size = 10  # Base size for version, locktime, etc.
#     tx_size = base_size + (num_inputs * input_size) + (num_outputs * output_size)
#     return tx_size


# def calculate_fee(fee_rate, tx_size):
#     """
#     Calculate the transaction fee based on size and fee rate.

#     :param fee_rate: Fee rate in satoshis per byte.
#     :param tx_size: Transaction size in bytes.
#     :return: Fee in satoshis.
#     """
#     return fee_rate * tx_size


@plugin.method("bumpchannelopen")
def bumpchannelopen(plugin, txid, vout, fee_rate, address, **kwargs):
    """
    Create a CPFP transaction for a specific parent output using lightning-utxopsbt.
    """
    if not txid:
        raise CPFPError("txid is required.")
    if vout is None:
        raise CPFPError("vout is required.")

    plugin.log(f"Input Parameters - txid: {txid}, vout: {vout}, fee_rate: {fee_rate}, address: {address}")

    # Step 1: Fetch the network information from the Lightning node
    info = plugin.rpc.getinfo()
    network = info.get('network')
    plugin.log(f"Network detected: {network}")

    #Found a number that works but only if fee rate is 5, if it's high then the feerate drops, if it's low, then the feerate goes up
    plugin.log(f"line 122 fee_rate before division: {fee_rate}")
    fee_rate = int(fee_rate/0.0004212)
    plugin.log(f"line 124 fee_rate after division: {fee_rate}")

    if not network:
        plugin.log("Network information is missing")
        raise CPFPError("Network information is missing.")

    # Step 2: Get list of available UTXOs from the Lightning node
    funds = plugin.rpc.listfunds()
    utxos = funds.get("outputs", [])
    if not utxos:
        raise CPFPError("No unspent transaction outputs found.")

    plugin.log("Available UTXOs:")
    for idx, utxo in enumerate(utxos):
        plugin.log(f"{idx}: txid={utxo['txid']} vout={utxo['output']} amount={utxo['amount_msat']} msat")

    plugin.log(f"line 132: txid variable contains this txid: {txid}")

    # Step 3: Calculate the total amount of confirmed and unreserved outputs
    total_sats = calculate_confirmed_unreserved_amount(funds)
    plugin.log(f"Total amount in confirmed and unreserved outputs: {total_sats} sats")

    # Step 4: Try to select an available, unreserved UTXO
    selected_utxo = None

    for utxo in utxos:
        if utxo["txid"] == txid and utxo["output"] == vout:
            if utxo.get("reserved", False):
                raise CPFPError(f"Selected utxo {txid}:{vout} is reserved.")
            else:
                selected_utxo = utxo
                break

        plugin.log(f"line 149: txid variable contains this txid: {txid}")

    if not selected_utxo:
        raise CPFPError(f"UTXO {txid}:{vout} not found.")
    plugin.log(f"Selected UTXO: txid={selected_utxo['txid']}, vout={selected_utxo['output']}")
    plugin.log(f"Contents of selected_utxo: {selected_utxo}")

    plugin.log(f"line 156: txid variable contains this txid: {txid}")

    # Step 5: Fetch UTXO details and convert amount
    amount_msat = selected_utxo["amount_msat"]
    if not amount_msat:
        raise CPFPError(f"UTXO {txid}:{vout} not found or already spent.")
    plugin.log(f"amount_msat type: {type(amount_msat)}, value: {amount_msat}")

    plugin.log(f"line 164: txid variable contains this txid: {txid}")

    amount = amount_msat // 1000  # Convert msat to satoshis
    plugin.log(f"Fetched UTXO: txid={selected_utxo['txid']}, vout={selected_utxo['output']}, amount={amount} sats")

    plugin.log(f"line 169: txid variable contains this txid: {txid}")


    # # Step 6: Calculate fee and recipient amount
    # # Estimate transaction size dynamically
    # input_size = 180  # Approximate size for a typical input (adjust if needed)
    # output_size = 34  # Typical size for an output
    # tx_size = input_size + output_size  # Number of inputs
    # plugin.log(f"Estimated transaction size: {tx_size} bytes")

    # fee = int(fee_rate * tx_size)

    # Step 6: Estimate transaction size and calculate fee
    # num_inputs = 1
    # num_outputs = 2  # One to destination and one for change (25,000 sats)

    # tx_size = estimate_tx_size(num_inputs=num_inputs, num_outputs=num_outputs, input_type="P2WPKH", output_type="P2WPKH")
    # plugin.log(f"Estimated transaction size: {tx_size} bytes")

    # fee = calculate_fee(fee_rate, tx_size)
    # plugin.log(f"Calculated fee: {fee} sats (Fee rate: {fee_rate} sat/vByte, Tx size: {tx_size} bytes)")

    # if fee >= amount:
    #     raise CPFPError("The fee exceeds the available amount in the UTXO.")

    # remaining_amount = amount - fee
    # plugin.log(f"Remaining amount after fee: {remaining_amount} sats, Amount: {amount}, Fee: {fee}")

    # # Step 7: Subtract emergency channel amount (25,000 sats) from recipient_amount
    # emergency_channel_amount = 25000  # Emergency channel amount in sats

    # if amount <= emergency_channel_amount:
    #     raise CPFPError("Not enough funds for fees and emergency reserve.")

    # recipient_amount = amount - emergency_channel_amount - calculated_fee # Subtract emergency channel

    # plugin.log(f"Reserve amount: {emergency_channel_amount} sats, Recipient amount: {recipient_amount} sats")


    # Step 8: Use `lightning-withdraw` to create and broadcast the transaction
    utxo_selector = [f"{selected_utxo['txid']}:{selected_utxo['output']}"]
    plugin.log(f"Bumping selected output using UTXO {utxo_selector}")

    # txid contains funding txid    
    plugin.log(f"line 213: txid variable contains this txid: {txid}")

    try:


        # rpc_result = plugin.rpc.txprepare(
        #     satoshi=recipient_amount,  # Or replace with the specific satoshi value if needed
        #     feerate=fee_rate,  # Adjust based on your desired feerate
        #     startweight=0,  # Default to 0 unless you have a specific weight
        #     utxos=utxo_selector,  # Pass the selected UTXOs here
        #     #reserve=72,  # Optional, default reserve period (adjust if needed)
        #     # reservedok=False,  # Optional, allow using reserved UTXOs if set to True
        #     # locktime=None,  # Optional, defaults to a recent block height
        #     # min_witness_weight=0,  # Optional, adjust based on UTXO witness weight
        #     excess_as_change=True,  # Optional, add change output for excess sats
        #     opening_anchor_channel=False
        # )


        # First time we call txprepare with 0 receiving amount
        rpc_result = plugin.rpc.txprepare(
            # outputs=[{address: recipient_amount}],
            outputs=[{address: 0}],
            utxos=utxo_selector,
            feerate=fee_rate
        )

        plugin.log(f"rpc_result: {rpc_result}")
        plugin.log(f"feerate: {fee_rate}")

        v0_psbt = plugin.rpc.setpsbtversion(
            psbt=rpc_result.get("psbt"),
            version=0
        )
        plugin.log(f"v0_psbt: {v0_psbt}")

        new_psbt= PartiallySignedTransaction.from_base64(v0_psbt.get("psbt"))

        fee = new_psbt.get_fee()
        plugin.log(f"fee: {fee}")

        plugin.rpc.unreserveinputs(
            psbt=rpc_result.get("psbt"),
        )

    except CPFPError as e:
        plugin.log(f"CPFPError occurred: {str(e)}")
        raise CPFPError("Error creating CPFP transaction.")
    except RpcError as e:
        plugin.log(f"RPC Error during withdrawal: {str(e)}")
        raise CPFPError(f"RPC Error while withdrawing funds: {str(e)}")
    except Exception as e:
        plugin.log(f"General error occurred while withdrawing: {str(e)}")
        raise CPFPError(f"Error while withdrawing funds: {str(e)}")


    # plugin.log(f"amount: {amount}, emergency_channel_amount: {emergency_channel_amount}, calculated_fee: {calculated_fee}")

    # Emergency channel amount in sats, cln will create an output of this amount
    # as long as we subtract it from the recipient amount
    emergency_refill_amount = 0
    if total_sats < 25000:
        emergency_refill_amount = 25000 - total_sats

    if amount <= emergency_refill_amount:
        raise CPFPError("Not enough funds for fees and emergency reserve.")

    recipient_amount = amount - emergency_refill_amount - fee # Subtract emergency channel
    plugin.log(f"Reserve amount: {emergency_refill_amount} sats, Recipient amount: {recipient_amount} sats")
    plugin.log(f"line 290 fee: {fee}")

    # Second time we call txprepare
    try:
        rpc_result = plugin.rpc.txprepare(
            outputs=[{address: recipient_amount}],
            utxos=utxo_selector,
            feerate=fee_rate
        )
        plugin.log(f"v0_psbt: {v0_psbt}")
        plugin.log(f"line 300 fee_rate: {fee_rate}")

        # plugin.rpc.unreserveinputs(
        #     psbt=rpc_result.get("psbt"),
        # )

    #     # rpc_result = plugin.rpc.withdraw(
    #     #     destination=address,
    #     #     satoshi=recipient_amount,
    #     #     feerate=fee_rate,
    #     #     utxos=utxo_selector
    #     # )

        # plugin.log(f"rpc_result: {json.dumps(rpc_result, indent=4)}")  # Log the full result

    except CPFPError as e:
        plugin.log(f"CPFPError occurred: {str(e)}")
        raise CPFPError("Error creating CPFP transaction.")
    except RpcError as e:
        plugin.log(f"RPC Error during withdrawal: {str(e)}")
        raise CPFPError(f"RPC Error while withdrawing funds: {str(e)}")
    except Exception as e:
        plugin.log(f"General error occurred while withdrawing: {str(e)}")
        raise CPFPError(f"Error while withdrawing funds: {str(e)}")

    # Step 9: Log and return the transaction details
    child_txid = rpc_result.get("txid")
    psbt = rpc_result.get("psbt")
    signed_psbt = ""
    
    # txid contains a new txid    
    plugin.log(f"line 320: txid variable contains this txid: {txid}")
    plugin.log(f"line 321: child_txid variable contains this txid: {child_txid}")

    # plugin.log(f"Broadcasted CPFP transaction with txid: {txid}")

    try:
        signed_v2_psbt = plugin.rpc.signpsbt(
            psbt=psbt
        )

        signed_v0_psbt = plugin.rpc.setpsbtversion(
            psbt=signed_v2_psbt.get("signed_psbt"),
            version=0
        )

        plugin.log(f"Signed PSBT (v2): {signed_v2_psbt}")
        plugin.log(f"Signed PSBT (v0): {signed_v0_psbt}")

        plugin.rpc.unreserveinputs(
            psbt=rpc_result.get("psbt"),
        )

    #     # rpc_result = plugin.rpc.withdraw(
    #     #     destination=address,
    #     #     satoshi=recipient_amount,
    #     #     feerate=fee_rate,
    #     #     utxos=utxo_selector
    #     # )

        # plugin.log(f"rpc_result: {json.dumps(rpc_result, indent=4)}")  # Log the full result

    except CPFPError as e:
        plugin.log(f"CPFPError occurred: {str(e)}")
        raise CPFPError("Error creating CPFP transaction.")
    except RpcError as e:
        plugin.log(f"RPC Error during withdrawal: {str(e)}")
        raise CPFPError(f"RPC Error while withdrawing funds: {str(e)}")
    except Exception as e:
        plugin.log(f"General error occurred while withdrawing: {str(e)}")
        raise CPFPError(f"Error while withdrawing funds: {str(e)}")

    child_v0_psbt = signed_v0_psbt.get("psbt")
    psbt_v0 = "'" + child_v0_psbt + "'"
    psbt_v2 = signed_v2_psbt.get("signed_psbt")

    # Prepare the final response
    response = {
        "message": "Please make sure to run bitcoin-cli finalizepsbt and analyzepsbt to verify "
        "the details before broadcasting the transaction",
        "finalize command": f'copy/paste this: bitcoin-cli finalizepsbt {psbt_v0} ',
        "analyze command": f'copy/paste this: bitcoin-cli analyzepsbt {psbt_v0} ',
        "signed_v2_psbt": psbt_v2,
        # "total_vsizes": total_vsizes,
        # "total_fees": total_fees,
        # "total_feerate": total_feerate
    }

    plugin.log(f"line 377: txid variable contains this txid: {txid}")
    plugin.log(f"line 378: child_txid variable contains this txid: {child_txid}")

    # First attempt using the bitcoin rpc_connection function:

    rpc_connection = connect_bitcoincli(
        rpc_user=plugin.get_option('bump_brpc_user'),
        rpc_password=plugin.get_option('bump_brpc_pass'),
        port=plugin.get_option('bump_brpc_port')
    )
    plugin.log(f"line 384: Contents of rpc_connection: {rpc_connection}")

    parsed_parent_hex = rpc_connection.getrawtransaction(txid)
    plugin.log(f"line 387: Contents of parsed_parent_hex: {parsed_parent_hex}")

    # # Hardcoded values, user should pass in their host, port, rpcuser and rpcpassword
    # rpc_connection = AuthServiceProxy("http://%s:%s@127.0.0.1:18443"%("__cookie__", "12bacf16e6963c18ddfe8fe18ac275300d1ea40ed4738216d89bcf3a1b707ed3"))
    # plugin.log(f"Contents of rpc_connection: {rpc_connection}")
    # parsed_parent_hex = rpc_connection.getrawtransaction(txid)
    # plugin.log(f"Contents of parsed_parent_hex: {parsed_parent_hex}")

    # Hardcoded values, user should pass in their host, port, rpcuser and rpcpassword
    # rpc_connection = AuthServiceProxy("http://%s:%s@127.0.0.1:18443"%("__cookie__", "12bacf16e6963c18ddfe8fe18ac275300d1ea40ed4738216d89bcf3a1b707ed3"))
    tx = rpc_connection.getrawtransaction(txid, True)
    # Calculate total inputs
    total_inputs = 0
    for vin in tx["vin"]:
        input_tx = rpc_connection.getrawtransaction(vin["txid"], True)
        total_inputs += input_tx["vout"][vin["vout"]]["value"]
    # Calculate total outputs
    total_outputs = sum(vout["value"] for vout in tx["vout"])
    # Calculate the fee
    parent_fee = total_inputs - total_outputs
    plugin.log(f"Contents of parent_fee: {parent_fee}")

    # Hardcoded values, user should pass in their host, port, rpcuser and rpcpassword
    # rpc_connection = AuthServiceProxy("http://%s:%s@127.0.0.1:18443"%("__cookie__", "12bacf16e6963c18ddfe8fe18ac275300d1ea40ed4738216d89bcf3a1b707ed3"))
    parent_tx_dict = rpc_connection.decoderawtransaction(parsed_parent_hex)
    parent_vsize = parent_tx_dict.get("vsize")
    plugin.log(f"Contents of parent_vsize: {parent_vsize}")
    parent_fee_rate = (parent_fee * 10**8) / parent_vsize  # sat/vB
    plugin.log(f"Contents of parent_fee_rate: {parent_fee_rate}")

    # Hardcoded values, user should pass in their host, port, rpcuser and rpcpassword
    # rpc_connection = AuthServiceProxy("http://%s:%s@127.0.0.1:18443"%("__cookie__", "12bacf16e6963c18ddfe8fe18ac275300d1ea40ed4738216d89bcf3a1b707ed3"))
    plugin.log(f"Contents of rpc_connection: {rpc_connection}")
    child_analyzed = rpc_connection.analyzepsbt(child_v0_psbt)
    child_fee = child_analyzed["fee"]
    child_vsize = child_analyzed["estimated_vsize"]
    child_feerate = child_analyzed["estimated_feerate"]
    plugin.log(f"Contents of child_fee: {child_fee}")
    plugin.log(f"Contents of child_vsize: {child_vsize}")
    plugin.log(f"Contents of child_feerate: {child_feerate}")

    total_vsizes = parent_vsize + child_vsize
    plugin.log(f"Contents of total_vsizes: {total_vsizes}")
    total_fees = (parent_fee + child_fee) * 10**8  # Convert fees to satoshis if in BTC
    plugin.log(f"Contents of total_fees: {total_fees}")
    total_feerate = total_fees / total_vsizes
    plugin.log(f"Contents of total_feerate: {total_feerate}")

    # Update the dictionary with new key-value pairs & Convert non-serializable objects to serializable formats
    response.update({
        "total_vsizes": int(total_vsizes) if total_vsizes is not None else 0,
        "total_fees": int(total_fees) if total_fees is not None else 0,
        "total_feerate": float(total_feerate) if total_feerate is not None else 0.0
    })

    plugin.log(f"Contents of response: {response}")

    # # Prepare the final response
    # response = {
    #     "message": "Please make sure to run bitcoin-cli finalizepsbt and analyzepsbt to verify "
    #     "the details before broadcasting the transaction",
    #     "finalize command": f'copy/paste this: bitcoin-cli finalizepsbt {psbt_v0} ',
    #     "analyze command": f'copy/paste this: bitcoin-cli analyzepsbt {psbt_v0} ',
    #     "signed_v2_psbt": psbt_v2,
    #     "total_vsizes": total_vsizes,
    #     "total_fees": total_fees,
    #     "total_feerate": total_feerate
    # }

    return response

plugin.run()
