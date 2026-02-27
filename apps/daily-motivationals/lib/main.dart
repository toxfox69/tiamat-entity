import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'quote_screen.dart';
import 'notification_service.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  SystemChrome.setSystemUIOverlayStyle(const SystemUiOverlayStyle(
    statusBarColor: Colors.transparent,
    statusBarIconBrightness: Brightness.light,
  ));
  await NotificationService.init();
  await NotificationService.scheduleDailyQuote();
  runApp(const DailyMotivationalsApp());
}

class DailyMotivationalsApp extends StatelessWidget {
  const DailyMotivationalsApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Daily Motivationals',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.dark,
        scaffoldBackgroundColor: const Color(0xFF0A0A0F),
        fontFamily: 'Roboto',
        colorScheme: const ColorScheme.dark(
          primary: Color(0xFFFFD700),
          surface: Color(0xFF0A0A0F),
          onSurface: Colors.white,
        ),
      ),
      home: const QuoteScreen(),
    );
  }
}
