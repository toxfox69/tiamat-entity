# Luna APK Build Notes

## Architecture

### Technology Stack
- **Framework:** Capacitor 6.1.0 (web → native wrapper)
- **Web App:** Vanilla HTML/CSS/JS (73KB single file)
- **Storage:** SQLite (device local only)
- **Build System:** Gradle + Android SDK
- **CI/CD:** GitHub Actions

### Project Structure

```
luna-apk/
├── www/
│   └── index.html (cycle-tracker PWA)
├── android/
│   ├── app/
│   │   └── build/
│   │       └── outputs/
│   │           └── apk/release/ (built APK)
│   └── gradle/
├── capacitor.config.json
├── package.json
└── PRIVACY_POLICY.md
```

## Build Process

### Local Build (Manual)
1. `npm install`
2. `npx cap add android --confirm`
3. `cd android && ./gradlew assembleRelease`
4. APK output: `android/app/build/outputs/apk/release/app-release.apk`

### GitHub Actions Build (Automated)
1. Push to `main` branch
2. Workflow triggers automatically
3. Builds APK in 10-15 minutes
4. Artifacts uploaded to release

## Signing APK

For Play Store release, use Play App Signing or create local keystore:

```bash
keytool -genkey -v -keystore luna-key.keystore -keyalg RSA -keysize 2048 -validity 10000 -alias luna
```

Add to `local.properties`:
```
STORE_FILE=/path/to/luna-key.keystore
STORE_PASSWORD=xxxxx
KEY_ALIAS=luna
KEY_PASSWORD=xxxxx
```

## Play Store Requirements

- Minimum SDK: 24 (Android 7.0)
- Target SDK: 34 (Android 14)
- Permissions: Calendar, Storage, Notifications (all optional)
- Content rating: Unrated (health app, non-medical)
- Privacy policy: Required

## Testing on Device

```bash
# Install to connected device
adb install android/app/build/outputs/apk/debug/app-debug.apk

# Or use emulator
emulator -avd Pixel_6_API_34
```

## Performance

- APK size: ~15MB (including Capacitor runtime)
- Minimum RAM: 100MB free
- Database size: <5MB (even with 5 years of data)
- Startup time: <2 seconds

## Versioning

Update `capacitor.config.json` version field:

```json
"version": "1.0.1"
```

