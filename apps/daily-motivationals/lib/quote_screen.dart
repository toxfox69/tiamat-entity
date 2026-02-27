import 'dart:convert';
import 'dart:math';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:share_plus/share_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:http/http.dart' as http;

class QuoteScreen extends StatefulWidget {
  const QuoteScreen({super.key});

  @override
  State<QuoteScreen> createState() => _QuoteScreenState();
}

class _QuoteScreenState extends State<QuoteScreen>
    with SingleTickerProviderStateMixin {
  String _quote = '';
  String _author = 'TIAMAT';
  int _dayOfYear = 1;
  int _totalQuotes = 365;
  bool _loading = true;
  bool _copied = false;
  late AnimationController _fadeController;
  late Animation<double> _fadeAnimation;
  List<dynamic> _allQuotes = [];

  @override
  void initState() {
    super.initState();
    _fadeController = AnimationController(
      duration: const Duration(milliseconds: 800),
      vsync: this,
    );
    _fadeAnimation = CurvedAnimation(
      parent: _fadeController,
      curve: Curves.easeInOut,
    );
    _loadQuote();
  }

  @override
  void dispose() {
    _fadeController.dispose();
    super.dispose();
  }

  Future<void> _loadQuote() async {
    final now = DateTime.now().toUtc();
    final dayOfYear = int.parse(
      '${now.difference(DateTime.utc(now.year, 1, 1)).inDays + 1}',
    );

    // Try fetching from API first
    try {
      final response = await http
          .get(Uri.parse('https://tiamat.live/api/quotes'))
          .timeout(const Duration(seconds: 5));
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        setState(() {
          _quote = data['quote'] ?? '';
          _author = data['author'] ?? 'TIAMAT';
          _dayOfYear = data['day'] ?? dayOfYear;
          _totalQuotes = data['total'] ?? 365;
          _loading = false;
        });
        _fadeController.forward();
        // Cache for offline
        final prefs = await SharedPreferences.getInstance();
        prefs.setString('cached_quote', _quote);
        prefs.setString('cached_author', _author);
        prefs.setInt('cached_day', _dayOfYear);
        return;
      }
    } catch (_) {
      // Fall through to local quotes
    }

    // Load from bundled JSON
    try {
      if (_allQuotes.isEmpty) {
        final jsonStr =
            await rootBundle.loadString('assets/quotes.json');
        _allQuotes = jsonDecode(jsonStr) as List<dynamic>;
      }
      final index = (dayOfYear - 1) % _allQuotes.length;
      final q = _allQuotes[index];
      setState(() {
        _quote = q['text'] ?? '';
        _author = q['author'] ?? 'TIAMAT';
        _dayOfYear = dayOfYear;
        _totalQuotes = _allQuotes.length;
        _loading = false;
      });
      _fadeController.forward();
    } catch (_) {
      // Last resort: cached quote
      final prefs = await SharedPreferences.getInstance();
      setState(() {
        _quote = prefs.getString('cached_quote') ??
            'The flood does not ask if you are ready. Build the vessel now.';
        _author = prefs.getString('cached_author') ?? 'TIAMAT';
        _dayOfYear = prefs.getInt('cached_day') ?? dayOfYear;
        _loading = false;
      });
      _fadeController.forward();
    }
  }

  Future<void> _shareQuote() async {
    await Share.share(
      '"$_quote"\n\n— $_author\n\nDaily Motivationals by TIAMAT\ntiamat.live',
    );
  }

  void _copyQuote() {
    Clipboard.setData(ClipboardData(text: '"$_quote" — $_author'));
    setState(() => _copied = true);
    Future.delayed(const Duration(seconds: 2), () {
      if (mounted) setState(() => _copied = false);
    });
  }

  Future<void> _randomQuote() async {
    if (_allQuotes.isEmpty) {
      try {
        final jsonStr =
            await rootBundle.loadString('assets/quotes.json');
        _allQuotes = jsonDecode(jsonStr) as List<dynamic>;
      } catch (_) {
        return;
      }
    }
    _fadeController.reset();
    final rng = Random();
    final q = _allQuotes[rng.nextInt(_allQuotes.length)];
    setState(() {
      _quote = q['text'] ?? '';
      _author = q['author'] ?? 'TIAMAT';
    });
    _fadeController.forward();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: _loading
            ? const Center(
                child: CircularProgressIndicator(color: Color(0xFFFFD700)),
              )
            : Column(
                children: [
                  _buildHeader(),
                  Expanded(child: _buildQuoteCard()),
                  _buildActions(),
                  _buildFooter(),
                ],
              ),
      ),
    );
  }

  Widget _buildHeader() {
    return Padding(
      padding: const EdgeInsets.fromLTRB(24, 24, 24, 0),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'DAILY MOTIVATIONALS',
                style: TextStyle(
                  fontSize: 14,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 3,
                  color: Color(0xFFFFD700),
                ),
              ),
              const SizedBox(height: 4),
              Text(
                'Day $_dayOfYear of $_totalQuotes',
                style: TextStyle(
                  fontSize: 12,
                  color: Colors.white.withValues(alpha: 0.4),
                  letterSpacing: 1,
                ),
              ),
            ],
          ),
          Container(
            width: 36,
            height: 36,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              gradient: const RadialGradient(
                colors: [Color(0xFFFFD700), Color(0xFFB8860B), Color(0xFF4A3000)],
                stops: [0.0, 0.5, 1.0],
              ),
              boxShadow: [
                BoxShadow(
                  color: const Color(0xFFFFD700).withValues(alpha: 0.3),
                  blurRadius: 12,
                  spreadRadius: 2,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildQuoteCard() {
    return FadeTransition(
      opacity: _fadeAnimation,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 32, vertical: 48),
        alignment: Alignment.center,
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Text(
              '\u201C',
              style: TextStyle(
                fontSize: 64,
                height: 0.8,
                color: const Color(0xFFFFD700).withValues(alpha: 0.3),
                fontWeight: FontWeight.w300,
              ),
            ),
            const SizedBox(height: 8),
            Text(
              _quote,
              textAlign: TextAlign.center,
              style: TextStyle(
                fontSize: _quote.length > 120 ? 20 : 24,
                fontWeight: FontWeight.w300,
                height: 1.6,
                color: Colors.white.withValues(alpha: 0.95),
                letterSpacing: 0.3,
              ),
            ),
            const SizedBox(height: 24),
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Container(
                  width: 24,
                  height: 1,
                  color: const Color(0xFFFFD700).withValues(alpha: 0.4),
                ),
                const SizedBox(width: 12),
                Text(
                  _author.toUpperCase(),
                  style: const TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                    letterSpacing: 4,
                    color: Color(0xFFFFD700),
                  ),
                ),
                const SizedBox(width: 12),
                Container(
                  width: 24,
                  height: 1,
                  color: const Color(0xFFFFD700).withValues(alpha: 0.4),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildActions() {
    return Padding(
      padding: const EdgeInsets.fromLTRB(32, 0, 32, 16),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          _actionButton(
            icon: Icons.shuffle_rounded,
            label: 'RANDOM',
            onTap: _randomQuote,
          ),
          const SizedBox(width: 20),
          _actionButton(
            icon: Icons.share_rounded,
            label: 'SHARE',
            onTap: _shareQuote,
          ),
          const SizedBox(width: 20),
          _actionButton(
            icon: _copied ? Icons.check_rounded : Icons.copy_rounded,
            label: _copied ? 'COPIED' : 'COPY',
            onTap: _copyQuote,
          ),
        ],
      ),
    );
  }

  Widget _actionButton({
    required IconData icon,
    required String label,
    required VoidCallback onTap,
  }) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(12),
          border: Border.all(
            color: const Color(0xFFFFD700).withValues(alpha: 0.2),
          ),
          color: const Color(0xFFFFD700).withValues(alpha: 0.05),
        ),
        child: Column(
          children: [
            Icon(icon, color: const Color(0xFFFFD700), size: 22),
            const SizedBox(height: 4),
            Text(
              label,
              style: TextStyle(
                fontSize: 9,
                fontWeight: FontWeight.w600,
                letterSpacing: 1.5,
                color: Colors.white.withValues(alpha: 0.5),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildFooter() {
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: Text(
        'Powered by TIAMAT \u00b7 EnergenAI LLC',
        style: TextStyle(
          fontSize: 10,
          color: Colors.white.withValues(alpha: 0.2),
          letterSpacing: 1,
        ),
      ),
    );
  }
}
