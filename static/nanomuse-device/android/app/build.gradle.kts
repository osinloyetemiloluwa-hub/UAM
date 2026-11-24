plugins {
    id("com.android.application")
    kotlin("android")
}

android {
    namespace = "dev.nanomuse.devicehost"
    compileSdk = 34

    defaultConfig {
        applicationId = "dev.nanomuse.devicehost"
        minSdk = 26          // java.time + foreground-service startForegroundService() baseline
        targetSdk = 34
        versionCode = 1
        versionName = "0.1.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            isShrinkResources = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_1_8
        targetCompatibility = JavaVersion.VERSION_1_8
    }
    kotlinOptions { jvmTarget = "1.8" }
}

dependencies {
    implementation("org.nanohttpd:nanohttpd:2.3.1")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")
    // org.json ships with Android — no extra dependency needed.
}
