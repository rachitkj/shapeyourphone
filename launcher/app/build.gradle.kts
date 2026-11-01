import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// Release signing comes from the environment (CI secrets); see scripts/make-release-key.sh.
val keystorePath: String? = System.getenv("SHAPE_KEYSTORE")

android {
    namespace = "io.github.rachitkj.shape"
    compileSdk = 36

    defaultConfig {
        applicationId = "io.github.rachitkj.shape"
        minSdk = 26
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"
    }

    signingConfigs {
        if (keystorePath != null) {
            create("release") {
                storeFile = file(keystorePath)
                storePassword = System.getenv("SHAPE_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("SHAPE_KEY_ALIAS")
                keyPassword = System.getenv("SHAPE_KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            if (keystorePath != null) signingConfig = signingConfigs.getByName("release")
        }
    }

    // config/default.json (shared with the Python toolkit) is the built-in home screen.
    sourceSets.getByName("main").assets.srcDir("../../config")

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    lint {
        abortOnError = true
        warningsAsErrors = false
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(JvmTarget.JVM_17)
    }
}

tasks.withType<Test>().configureEach {
    // Rule vectors shared with tests/test_launcher_config.py
    systemProperty("shape.vectors", rootProject.file("../tests/vectors/rules.json").absolutePath)
}

dependencies {
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
}
