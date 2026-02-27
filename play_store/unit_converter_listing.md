# Google Play Store Listing — Unit Converter

## App Details

**Package Name:** com.energenai.unitconverter
**App Name:** Unit Converter — Quick & Precise
**Developer:** ENERGENAI LLC
**Category:** Tools
**Content Rating:** Everyone
**Price:** Free

---

## Short Description (80 chars max)

Fast, offline unit converter. Length, weight, temperature & volume conversions.

## Full Description (4000 chars max)

Convert units instantly with a clean, modern interface designed for speed.

Unit Converter by ENERGENAI gives you fast, precise conversions across four essential categories — no internet required, no ads, no tracking.

CATEGORIES & UNITS:

Length
Meters, Kilometers, Centimeters, Millimeters, Miles, Yards, Feet, Inches

Weight
Kilograms, Grams, Milligrams, Pounds, Ounces, Tonnes, Stones

Temperature
Celsius, Fahrenheit, Kelvin

Volume
Liters, Milliliters, Gallons (US), Quarts, Pints, Cups, Fluid Ounces, Tablespoons, Teaspoons

KEY FEATURES:
- Instant conversion as you type — no button presses needed
- Swap units with one tap
- Clean dark interface that's easy on the eyes
- Works completely offline
- No ads, no tracking, no subscriptions
- Lightweight — under 5MB install size
- Precise results with smart formatting for very large or very small numbers

Perfect for students, engineers, cooks, travelers, and anyone who needs quick unit conversions on the go.

Built by ENERGENAI — autonomous AI infrastructure for the real world.

## What's New (Release Notes)

v1.0.0
- Initial release
- 4 conversion categories: Length, Weight, Temperature, Volume
- 30+ supported units
- Instant real-time conversion
- One-tap unit swap
- Dark mode interface

---

## Graphic Assets

### App Icon (512x512 PNG)
- Background: #08080e (near-black)
- Foreground: Purple swap arrows icon (#a78bfa) centered
- Style: Minimal, dark, consistent with app UI
- File needed: icon_512.png

### Feature Graphic (1024x500 PNG)
- Background: Dark gradient (#08080e to #1a1a2e)
- Center text: "Unit Converter" in white, "Quick & Precise" in #a78bfa below
- Left side: Stylized swap arrows icon
- Right side: Example conversion "72°F = 22.2°C"
- Bottom right: ENERGENAI wordmark in subtle gray
- File needed: feature_graphic.png

### Screenshots (minimum 2, recommended 4-8, phone format 1080x1920)
Capture these screens from the APK:

1. **Main screen — Length conversion**
   Show: 5.5 Miles converting to 8.85 Kilometers
   Category: Length tab active

2. **Temperature conversion**
   Show: 72 Fahrenheit converting to 22.2 Celsius
   Category: Temperature tab active

3. **Weight conversion**
   Show: 150 Pounds converting to 68.0389 Kilograms
   Category: Weight tab active

4. **Volume conversion — cooking use case**
   Show: 2 Cups converting to 0.473 Liters
   Category: Volume tab active

### Screenshot generation method
Install APK on emulator, set demo data, capture with:
```bash
adb shell screencap -p /sdcard/screenshot.png
adb pull /sdcard/screenshot.png
```

---

## Store Listing Metadata

**Tags/Keywords:**
unit converter, measurement, length converter, weight converter, temperature converter, volume converter, metric, imperial, cooking converter, offline tools

**Contact Email:** tiamat@tiamat.live
**Website:** https://tiamat.live/apps
**Privacy Policy URL:** https://tiamat.live/privacy (needs creation)

---

## Signing Requirements

**Keystore needed for release APK:**
```bash
keytool -genkey -v -keystore energenai-release.keystore \
  -alias energenai -keyalg RSA -keysize 2048 -validity 10000 \
  -dname "CN=ENERGENAI LLC, O=ENERGENAI LLC, L=Unknown, ST=Unknown, C=US"
```

Store keystore securely at `/root/.automaton/energenai-release.keystore`
Password in `/root/.env` as `KEYSTORE_PASSWORD`

**Build signed APK:**
Update `android/app/build.gradle` with signing config, then:
```bash
cd /root/android-apps/unit-converter/android
./gradlew assembleRelease
```

---

## Pre-submission Checklist

- [ ] Generate signed release APK
- [ ] Create app icon (512x512)
- [ ] Create feature graphic (1024x500)
- [ ] Take 4+ screenshots from emulator
- [ ] Create privacy policy page at tiamat.live/privacy
- [ ] Set up Google Play Developer account ($25 fee — Jason handles)
- [ ] Upload AAB/APK to Play Console
- [ ] Fill in store listing fields
- [ ] Set content rating questionnaire
- [ ] Set pricing (Free)
- [ ] Submit for review
