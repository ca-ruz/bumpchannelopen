import os
from pyln.testing.fixtures import *  # noqa: F403
from pyln.testing.utils import sync_blockheight, FUNDAMOUNT, BITCOIND_CONFIG

pluginopt = {'plugin': os.path.join(os.path.dirname(__file__), "bumpchannelopen.py")}

def test_bumpchannelopen(node_factory):
    # Set a low PeerThread interval so we can test quickly.
    opts = {'disable-plugin': "clnrest",
            'bump_brpc_user': BITCOIND_CONFIG["rpcuser"],
            'bump_brpc_pass': BITCOIND_CONFIG["rpcpassword"],
            'bump_brpc_port': BITCOIND_CONFIG["rpcport"]
        }
    opts.update(pluginopt)
    l1, l2 = node_factory.get_nodes(2, opts=opts)
    l2id = l2.info['id']

    nodes = [l1,l2]

    l1.rpc.connect(l2.info['id'], 'localhost', l2.port)

    bitcoind = l1.bitcoin
    # If we got here, we want to fund channels
    addr = l1.rpc.newaddr()['bech32']
    bitcoind.rpc.sendtoaddress(addr, (FUNDAMOUNT + 1000000) / 10**8)

    bitcoind.generate_block(1)
    sync_blockheight(bitcoind, nodes)

    txid = l1.rpc.fundchannel(l2.info['id'], FUNDAMOUNT)['txid']




    print(f"DEBUG 1 get txid = {txid}")

    funding_txid = l1.rpc.listfunds().get("channels", [])[0].get("funding_txid")
    print (f"DEBUG 2 get funding_txid = {funding_txid}")

    listfunds_result=l1.rpc.listfunds()
    print(f"DEBUG 2.5 get listfunds_result= {listfunds_result}")

    funding_vout = l1.rpc.listfunds().get("channels", [])[0].get("funding_output")
    print (f"DEBUG 3 get funding_vout = {funding_vout}")





    # A for loop to get all the output txids and vouts might be a better solution

    output_txid_1 = l1.rpc.listfunds().get("outputs", [])[0].get("txid")
    print (f"DEBUG 4 get output_txid_1 = {output_txid_1}")

    output_vout_1 = l1.rpc.listfunds().get("outputs", [])[0].get("output")
    print (f"DEBUG 5 get output_vout_1 = {output_vout_1}")

    output_txid_2 = l1.rpc.listfunds().get("outputs", [])[1].get("txid")
    print (f"DEBUG 6 get utput_txid_2 = {output_txid_2}")

    output_vout_2 = l1.rpc.listfunds().get("outputs", [])[1].get("output")
    print (f"DEBUG 7 get vout_output_vout_2 = {output_vout_2}")



    # Get the proper vout to pass in bumpchannelopen
    # Compare funding_txid with output_txid_1 and output_txid_2
    if funding_txid == output_txid_1:
        matching_vout = output_vout_1
    elif funding_txid == output_txid_2:
        matching_vout = output_vout_2
    else:
        matching_vout = None  # Handle case where no match is found

    print(f"DEBUG 8 correct vout = {matching_vout}")




    # when
    s1 = l1.rpc.bumpchannelopen(
        txid=funding_txid,
        vout=matching_vout,
        fee_rate=5,
        address=l1.rpc.newaddr()['bech32'],
    )

    l2.stop()  # we stop l2 and wait for l1 to see that
    l1.daemon.wait_for_log(f".*{l2id}.*Peer connection lost.*")
    wait_for(lambda: l1.rpc.listpeers(l2id)['peers'][0]['connected'] is False)
    l1.daemon.wait_for_log("Peerstate wrote to datastore")
    s2 = l1.rpc.bumpchannelopen()

    # then
    avail1 = int(re.search(' ([0-9]*)% ', s1['channels'][2]).group(1))
    avail2 = int(re.search(' ([0-9]*)% ', s2['channels'][2]).group(1))
    assert(avail1 == 100)
    assert(avail2 > 0 and avail2 < avail1)