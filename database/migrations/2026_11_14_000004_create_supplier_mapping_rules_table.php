<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('supplier_mapping_rules', function (Blueprint $table) {
            $table->id();
            $table->foreignId('supplier_id')->constrained()->cascadeOnDelete();
            // Where the rule applies: category, color, size, price, field_override, ...
            $table->string('scope', 40);
            $table->json('rule');
            $table->boolean('is_active')->default(true);
            $table->timestamps();

            $table->index(['supplier_id', 'scope']);
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('supplier_mapping_rules');
    }
};
