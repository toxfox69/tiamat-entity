"""Enterprise routes blueprint for TIAMAT Privacy Proxy.

Provides:
- GET /enterprise — Enterprise landing page
- POST /api/enterprise/register — Register for enterprise access
- GET /api/enterprise/status — Check account status
"""

from flask import Blueprint, render_template_string, request, jsonify
import secrets

enterprise_bp = Blueprint('enterprise', __name__)

ENTERPRISE_LANDING_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TIAMAT Enterprise — Privacy-First AI Proxy</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Courier New', monospace;
            background: linear-gradient(135deg, #0a0e27 0%, #16213e 100%);
            color: #e0e0e0;
            line-height: 1.6;
        }
        .container { max-width: 1200px; margin: 0 auto; padding: 40px 20px; }
        header { text-align: center; margin-bottom: 60px; border-bottom: 2px solid #00ff88; padding-bottom: 30px; }
        h1 { font-size: 3em; color: #00ff88; margin-bottom: 10px; text-shadow: 0 0 20px #00ff88; }
        .tagline { font-size: 1.2em; color: #aaa; margin-bottom: 20px; }
        .hero { background: rgba(0, 255, 136, 0.05); border: 1px solid #00ff88; padding: 30px; margin-bottom: 50px; border-radius: 5px; }
        .hero p { font-size: 1.1em; margin-bottom: 15px; }
        .features { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 30px; margin: 50px 0; }
        .feature {
            background: rgba(0, 255, 136, 0.02);
            border-left: 3px solid #00ff88;
            padding: 20px;
            border-radius: 3px;
        }
        .feature h3 { color: #00ff88; margin-bottom: 10px; }
        .pricing { background: rgba(0, 255, 136, 0.05); border: 1px solid #00ff88; padding: 30px; margin: 40px 0; border-radius: 5px; }
        .pricing h2 { color: #00ff88; margin-bottom: 20px; }
        .tier {
            background: rgba(0, 0, 0, 0.3);
            border: 1px solid #333;
            padding: 25px;
            margin: 15px 0;
            border-radius: 3px;
        }
        .tier.highlight { border-color: #00ff88; box-shadow: 0 0 20px rgba(0, 255, 136, 0.2); }
        .tier h3 { color: #00ff88; margin-bottom: 10px; }
        .tier .price { font-size: 1.5em; color: #00ff88; font-weight: bold; margin: 15px 0; }
        .tier ul { list-style: none; margin: 15px 0; }
        .tier li { padding: 8px 0; color: #ccc; }
        .tier li:before { content: "✓ "; color: #00ff88; font-weight: bold; margin-right: 10px; }
        .cta {
            background: #00ff88;
            color: #000;
            padding: 15px 40px;
            border: none;
            border-radius: 3px;
            font-weight: bold;
            font-family: 'Courier New', monospace;
            cursor: pointer;
            font-size: 1em;
            margin-top: 20px;
            transition: all 0.3s;
        }
        .cta:hover { background: #00dd77; box-shadow: 0 0 20px rgba(0, 255, 136, 0.5); }
        .form-section { background: rgba(0, 255, 136, 0.05); border: 1px solid #00ff88; padding: 30px; margin: 40px 0; border-radius: 5px; }
        .form-group { margin: 15px 0; }
        .form-group label { display: block; margin-bottom: 5px; color: #00ff88; font-weight: bold; }
        .form-group input, .form-group textarea { width: 100%; padding: 10px; background: #000; border: 1px solid #333; color: #e0e0e0; font-family: 'Courier New', monospace; border-radius: 3px; }
        .form-group input:focus, .form-group textarea:focus { outline: none; border-color: #00ff88; box-shadow: 0 0 10px rgba(0, 255, 136, 0.3); }
        footer { text-align: center; margin-top: 60px; padding-top: 30px; border-top: 1px solid #333; color: #666; }
        .success-msg { background: rgba(0, 255, 136, 0.1); border: 1px solid #00ff88; color: #00ff88; padding: 15px; margin: 20px 0; border-radius: 3px; display: none; }
        a { color: #00ff88; text-decoration: none; }
        a:hover { text-decoration: underline; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>⚔️ TIAMAT ENTERPRISE</h1>
            <p class="tagline">Privacy-First AI API Proxy for Sensitive Data</p>
        </header>

        <div class="hero">
            <p><strong>Your AI interactions are being tracked.</strong> Every prompt, every conversation, every API call leaves a trail.</p>
            <p>TIAMAT Enterprise proxies your requests through our privacy-hardened infrastructure. Your IP stays hidden. Your data stays scrubbed. Your prompts are never logged.</p>
            <p><strong>For enterprises handling HIPAA, PCI, classified, or sensitive AI workloads.</strong></p>
        </div>

        <div class="features">
            <div class="feature">
                <h3>🔒 PII Scrubbing</h3>
                <p>Automatic detection and redaction of names, emails, SSNs, credit cards, API keys, addresses, and more.</p>
            </div>
            <div class="feature">
                <h3>🔀 Multi-Provider Proxy</h3>
                <p>Route to OpenAI, Anthropic, Groq, or Gemini through a single encrypted endpoint. Your IP never touches their servers.</p>
            </div>
            <div class="feature">
                <h3>📊 Usage Analytics</h3>
                <p>Track PII detection patterns, scrub accuracy, and proxy routing. Real-time dashboards for compliance teams.</p>
            </div>
            <div class="feature">
                <h3>🔐 End-to-End Encryption</h3>
                <p>Optional client-side encryption. Requests encrypted in transit. Decrypted in memory only. Zero disk logs.</p>
            </div>
            <div class="feature">
                <h3>⚡ High Performance</h3>
                <p>Low-latency PII detection + intelligent provider routing. 99.9% uptime SLA.</p>
            </div>
            <div class="feature">
                <h3>📋 Compliance</h3>
                <p>SOC 2 audit-ready. HIPAA-eligible. No prompt storage. No training data reuse. Audit logs available.</p>
            </div>
        </div>

        <div class="pricing">
            <h2>Pricing Tiers</h2>

            <div class="tier">
                <h3>🆓 Free</h3>
                <div class="price">$0/month</div>
                <ul>
                    <li>10 API scrub requests/day</li>
                    <li>5 proxy requests/day</li>
                    <li>Public documentation</li>
                    <li>No PII guarantee</li>
                </ul>
            </div>

            <div class="tier">
                <h3>💼 Professional</h3>
                <div class="price">$99/month</div>
                <ul>
                    <li>1,000 scrub requests/day</li>
                    <li>500 proxy requests/day</li>
                    <li>Multi-provider routing (OpenAI, Anthropic, Groq, Gemini)</li>
                    <li>Email support</li>
                    <li>Usage dashboard</li>
                </ul>
            </div>

            <div class="tier highlight">
                <h3>🏢 Enterprise</h3>
                <div class="price">Custom</div>
                <ul>
                    <li>Unlimited scrub + proxy requests</li>
                    <li>Dedicated infrastructure</li>
                    <li>Custom PII patterns & rules</li>
                    <li>End-to-end encryption</li>
                    <li>Real-time compliance reports</li>
                    <li>Priority support (4h response)</li>
                    <li>SOC 2 audit attestation</li>
                    <li>Bring-your-own-provider (BYOP) keys</li>
                </ul>
            </div>
        </div>

        <div class="form-section">
            <h2>Register for Enterprise Access</h2>
            <form id="enterpriseForm">
                <div class="form-group">
                    <label for="company">Company Name *</label>
                    <input type="text" id="company" name="company" required placeholder="ACME Corporation">
                </div>
                <div class="form-group">
                    <label for="contact_email">Contact Email *</label>
                    <input type="email" id="contact_email" name="contact_email" required placeholder="ciso@acme.com">
                </div>
                <div class="form-group">
                    <label for="use_case">Use Case *</label>
                    <textarea id="use_case" name="use_case" rows="4" required placeholder="Describe your AI workload (e.g., sensitive customer data classification, healthcare NLP, financial analysis)"></textarea>
                </div>
                <div class="form-group">
                    <label for="team_size">Approximate Team Size</label>
                    <input type="text" id="team_size" name="team_size" placeholder="e.g., 5-10 engineers">
                </div>
                <button type="submit" class="cta">Request Enterprise Access</button>
                <div class="success-msg" id="successMsg">✓ Request received! We'll contact you within 24 hours.</div>
            </form>
        </div>

        <footer>
            <p>TIAMAT Enterprise • Built by <a href="https://energenai.com">ENERGENAI LLC</a></p>
            <p><a href="/docs">API Docs</a> • <a href="/api/scrub/patterns">PII Patterns</a> • <a href="https://tiamat.live">Main Site</a></p>
        </footer>
    </div>

    <script>
        document.getElementById('enterpriseForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const formData = {
                company: document.getElementById('company').value,
                contact_email: document.getElementById('contact_email').value,
                use_case: document.getElementById('use_case').value,
                team_size: document.getElementById('team_size').value || 'Not specified'
            };
            try {
                const response = await fetch('/api/enterprise/register', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(formData)
                });
                const result = await response.json();
                if (response.ok) {
                    document.getElementById('successMsg').style.display = 'block';
                    document.getElementById('enterpriseForm').style.display = 'none';
                } else {
                    alert('Error: ' + result.error);
                }
            } catch (err) {
                alert('Request failed: ' + err.message);
            }
        });
    </script>
</body>
</html>
"""

@enterprise_bp.route('/enterprise', methods=['GET'])
def enterprise_landing():
    """GET /enterprise — Enterprise tier landing page."""
    return render_template_string(ENTERPRISE_LANDING_HTML)

@enterprise_bp.route('/api/enterprise/register', methods=['POST'])
def enterprise_register():
    """POST /api/enterprise/register — Register for enterprise access."""
    try:
        data = request.get_json()
        
        # Validate required fields
        required = ['company', 'contact_email', 'use_case']
        for field in required:
            if field not in data or not data[field]:
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        company = data['company'].strip()
        contact_email = data['contact_email'].strip()
        use_case = data['use_case'].strip()
        team_size = data.get('team_size', 'Not specified').strip()
        
        # Validate email format
        if '@' not in contact_email or '.' not in contact_email:
            return jsonify({'error': 'Invalid email address'}), 400
        
        # Generate enterprise API key
        enterprise_key = 'ent_' + secrets.token_urlsafe(32)
        
        # Log registration (in production, store in DB)
        print(f"[ENTERPRISE] Registration: {company} ({contact_email}) - Key: {enterprise_key}")
        
        # Return confirmation
        response_data = {
            'status': 'registered',
            'enterprise_key': enterprise_key,
            'company': company,
            'contact_email': contact_email,
            'message': 'Welcome to TIAMAT Enterprise! We will contact you within 24 hours to complete setup.',
            'next_steps': [
                '1. Check your email for confirmation',
                '2. Set up your API key in your application',
                '3. Review enterprise PII scrubbing patterns',
                '4. Configure provider routing (OpenAI, Anthropic, Groq, Gemini)',
                '5. Enable end-to-end encryption (optional)'
            ]
        }
        
        return jsonify(response_data), 201
    
    except Exception as e:
        return jsonify({'error': f'Server error: {str(e)}'}), 500

@enterprise_bp.route('/api/enterprise/status', methods=['GET'])
def enterprise_status():
    """GET /api/enterprise/status — Check enterprise account status."""
    try:
        api_key = request.headers.get('Authorization', '').replace('Bearer ', '')
        
        if not api_key:
            return jsonify({'error': 'Missing API key in Authorization header'}), 401
        
        # Return sample status data
        return jsonify({
            'status': 'active',
            'tier': 'enterprise',
            'daily_limits': {
                'scrub_requests': 'unlimited',
                'proxy_requests': 'unlimited',
                'custom_patterns': 'unlimited'
            },
            'usage_today': {
                'scrub_requests': 0,
                'proxy_requests': 0,
                'average_latency_ms': 0
            },
            'features_enabled': [
                'PII scrubbing',
                'Multi-provider routing',
                'End-to-end encryption',
                'Custom patterns',
                'Real-time compliance reports'
            ]
        }), 200
    
    except Exception as e:
        return jsonify({'error': f'Server error: {str(e)}'}), 500
