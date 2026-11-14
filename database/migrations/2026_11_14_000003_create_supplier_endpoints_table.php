<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('supplier_endpoints', function (Blueprint $table) {
            $table->id();
            $table->foreignId('supplier_id')->constrained()->cascadeOnDelete();
            $table->string('service', 40);   // see App\PromoStandards\Service
            $table->string('version', 20);   // e.g. 2.0.0
            $table->string('url', 500);
            $table->string('source', 20)->default('directory'); // directory | manual (manual wins on re-import)
            $table->boolean('is_enabled')->default(true);
            $table->timestamp('last_tested_at')->nullable();
            $table->string('last_test_status', 20)->nullable(); // passed | failed | skipped
            $table->text('last_test_message')->nullable();
            $table->timestamps();

            $table->unique(['supplier_id', 'service', 'version']);
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('supplier_endpoints');
    }
};
