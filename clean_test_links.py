import os
import dotenv
import razorpay

dotenv.load_dotenv()
client = razorpay.Client(auth=(os.getenv("RAZORPAY_KEY_ID"), os.getenv("RAZORPAY_KEY_SECRET")))

res = client.payment_link.all({"count": 50})
active = [l for l in res.get("payment_links", []) if l.get("status") in ("created", "issued")]
print(f"Found {len(active)} active links to cancel...")

for l in active:
    link_id = l["id"]
    try:
        client.payment_link.cancel(link_id)
        print(f"  [CANCELLED] {link_id}")
    except Exception as e:
        print(f"  [ERROR] {link_id}: {e}")

print("Cleanup complete! Active quota freed.")
