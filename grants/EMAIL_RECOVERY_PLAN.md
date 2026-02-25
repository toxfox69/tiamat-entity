# Email Infrastructure Status — Feb 25, 2026

## DIAGNOSIS: NO EMERGENCY — Both Domains Active

### energenai.org
- **Registrar:** Tucows Domains Inc. (privacy via Contact Privacy Inc.)
- **Created:** January 25, 2025
- **Expires:** January 25, 2027 (11 months remaining)
- **Status:** ACTIVE (ok, icann.org/epp#ok)
- **DNS:** ns1/ns2/ns3.systemdns.com (Tucows/Hover)
- **MX:** mx.energenai.org.cust.b.hostedemail.com (Tucows hosted email)
- **SPF:** v=spf1 include:_spf.hostedemail.com ~all

### tiamat.live
- **Registrar:** Namecheap
- **DNS:** dns1/dns2.registrar-servers.com (Namecheap)
- **MX:** eforward1-5.registrar-servers.com (Namecheap forwarding)
- **SPF:** v=spf1 include:spf.efwd.registrar-servers.com ~all
- **Current catch-all:** *@tiamat.live → tiamat.entity.prime@gmail.com

---

## OPTION A — Use energenai.org Email (RECOMMENDED for Federal)

energenai.org already has MX and SPF configured via Tucows/hostedemail.com.

**Action needed:**
1. Log into your Tucows/Hover registrar account
2. Check if email accounts are already provisioned (jason@energenai.org, etc.)
3. If not, set up an email address (Tucows hosted email is typically included or ~$20/yr)
4. Test send/receive

**Pros:**
- Most professional for federal contacts (company LLC domain)
- MX + SPF already configured = deliverability ready
- Matches your UEI/SAM registration

**For USSOCOM email, send from:** `jason@energenai.org` or `director@energenai.org`

---

## OPTION B — Use tiamat.live (FAST BACKUP)

tiamat.live already has email forwarding working (catch-all → Gmail).

**For sending FROM @tiamat.live:**
- Namecheap email forwarding only handles RECEIVING
- For SENDING, you'd need either:
  1. SendGrid (already configured) with verified sender domain
  2. Gmail "Send mail as" with SMTP relay
  3. Namecheap Professional Business Email (~$22/yr)

**Pros:**
- Shows the product domain to USSOCOM (tiamat.live = live demo)
- Forwarding already works

**Cons:**
- Not the LLC/company domain
- "tiamat.live" is less conventional than "energenai.org" for federal comms

---

## OPTION C — Both (BEST)

Use energenai.org for formal correspondence (USSOCOM, DARPA, NSF).
Use tiamat.live for technical demos and product-facing comms.

---

## RECOMMENDATION

**Use energenai.org — it's alive, has email configured, and matches your SAM/UEI.**

1. Log into your registrar (Tucows — probably Hover.com, check your email for receipts)
2. Verify email is active or activate it (~$0-20/yr)
3. Send USSOCOM email from jason@energenai.org
4. Include tiamat.live links in the email body for the live demo

This is the strongest combination: formal LLC identity + live product proof.
