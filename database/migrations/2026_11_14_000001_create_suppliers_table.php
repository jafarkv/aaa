<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('suppliers', function (Blueprint $table) {
            $table->id();
            $table->string('name');
            $table->string('slug')->unique();
            // Code from the PromoStandards directory; null for suppliers added by hand.
            $table->string('promostandards_code')->nullable()->index();
            $table->string('type', 20)->default('promostandards'); // promostandards | manual
            // draft -> testing -> ready -> paused. Only a Catalog lead moves a supplier to "ready".
            $table->string('status', 20)->default('draft');
            $table->string('account_number')->nullable();
            // First productId returned by Product Data; reused to probe Inventory, Pricing and Media.
            $table->string('sample_product_id')->nullable();
            // Politeness limits so we never get blocked: parallel calls and delay between calls.
            $table->unsignedSmallInteger('concurrency_limit')->default(2);
            $table->unsignedInteger('request_delay_ms')->default(250);
            // Suppliers are never deleted, only deactivated, so history stays traceable.
            $table->boolean('is_active')->default(true);
            $table->timestamp('deactivated_at')->nullable();
            $table->timestamps();
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('suppliers');
    }
};
