pluginManagement { repositories { google(); mavenCentral(); gradlePluginPortal() } }
dependencyResolutionManagement { repositories { google(); mavenCentral() } }
rootProject.name = "NanoMuseDeviceHost"
include(":app")

plugins {
    id("com.android.application") version "8.5.2" apply false
    kotlin("android") version "1.9.24" apply false
}
