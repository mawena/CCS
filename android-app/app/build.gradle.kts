plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
}

android {
    namespace = "com.mawena.ccs"
    compileSdk = 36

    defaultConfig {
        // Même identifiant que l'ancienne appli Flutter : la mise à jour s'installe par-dessus.
        applicationId = "com.mawena.ccs"
        minSdk = 26
        targetSdk = 36
        // Toujours croissant (l'appli Flutter 0.26.1 avait le numéro 27).
        versionCode = 36
        versionName = "1.1.0"
    }

    // Clé d'origine (celle de l'appli déjà installée), fournie par Codemagic dans CCS_KEYSTORE ;
    // sans elle, la clé de débogage de la machine qui construit.
    val cleCcs = System.getenv("CCS_KEYSTORE")?.let { file(it) }?.takeIf { it.length() > 0 }
    signingConfigs {
        if (cleCcs != null) {
            create("ccs") {
                storeFile = cleCcs
                storePassword = "android"
                keyAlias = "androiddebugkey"
                keyPassword = "android"
            }
        }
    }

    buildTypes {
        release {
            signingConfig = signingConfigs.getByName(if (cleCcs != null) "ccs" else "debug")
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    packaging {
        resources.excludes += setOf("/META-INF/{AL2.0,LGPL2.1}", "/META-INF/versions/9/previous-compilation-data.bin")
    }

    testOptions {
        unitTests.isReturnDefaultValues = true
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.navigation.compose)
    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.ui.tooling.preview)
    implementation(libs.compose.material3)
    implementation(libs.compose.icons.extended)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.kotlinx.serialization.json)
    implementation(libs.okhttp)
    implementation(libs.termux.terminal.emulator)
    implementation(libs.termux.terminal.view)
    debugImplementation(libs.compose.ui.tooling)

    testImplementation(libs.junit)
    testImplementation(libs.kotlinx.coroutines.test)
    testImplementation(libs.okhttp.mockwebserver)
}
